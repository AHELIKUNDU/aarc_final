"""
AARC Analytics API (Step 3)
---------------------------
Read-only endpoints on top of the data stored by POST /upload:

  GET /analytics/uploads   - list of uploaded files (history)
  GET /analytics/summary   - Low/Medium/High counts, KPIs, per-category breakdown
  GET /analytics/risks     - filterable, sortable, paginated list of risk items
  GET /analytics/insights  - plain-English reasoning: what drives the risk

Every endpoint accepts an optional ?upload_id=. If omitted, the most recent
processed upload is used.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ProductRisk, UploadRecord

router = APIRouter(prefix="/analytics", tags=["Analytics"])

LEVELS = ("Low", "Medium", "High")

# Thresholds used to count "risk drivers" in /insights.
# They mirror the main rules in risk.py (rating < 3.0 and discount >= 40%).
LOW_RATING_LIMIT = 3.0
HEAVY_DISCOUNT_LIMIT = 40.0


# ============================== HELPERS ==================================

def _resolve_upload(db: Session, upload_id: Optional[int]) -> UploadRecord:
    """Return the requested upload, or the latest processed one."""
    if upload_id is None:
        record = db.scalars(
            select(UploadRecord)
            .where(UploadRecord.status == "processed")
            .order_by(UploadRecord.id.desc())
        ).first()
        if record is None:
            raise HTTPException(
                status_code=404,
                detail="No processed uploads yet. Upload a CSV with POST /upload first.",
            )
        return record

    record = db.get(UploadRecord, upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Upload {upload_id} not found.")
    if record.status != "processed":
        raise HTTPException(
            status_code=409,
            detail=f"Upload {upload_id} has status '{record.status}' and has no results.",
        )
    return record


def _pct(part: int, whole: int) -> float:
    return round(part * 100 / whole, 1) if whole else 0.0


def _item(r: ProductRisk) -> dict:
    return {
        "id": r.id,
        "product_name": r.product_name,
        "category": r.category,
        "rating": r.rating,
        "price": r.price,
        "discount": r.discount,
        "risk_score": r.risk_score,
        "risk_level": r.risk_level,
        "reasoning": r.reasoning,
    }


def _upload_info(record: UploadRecord) -> dict:
    return {
        "id": record.id,
        "filename": record.filename,
        "uploaded_at": record.uploaded_at.isoformat() if record.uploaded_at else None,
        "total_rows": record.total_rows,
        "processed_rows": record.processed_rows,
        "status": record.status,
    }


# ============================== ENDPOINTS ================================

@router.get("/uploads")
def list_uploads(db: Session = Depends(get_db)):
    """All uploads, newest first."""
    records = db.scalars(select(UploadRecord).order_by(UploadRecord.id.desc())).all()
    return [_upload_info(r) for r in records]


@router.get("/summary")
def risk_summary(upload_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Total risk summary: KPI numbers + Low/Medium/High counts + per-category breakdown."""
    record = _resolve_upload(db, upload_id)

    # Overall counts per level
    rows = db.execute(
        select(ProductRisk.risk_level, func.count())
        .where(ProductRisk.upload_id == record.id)
        .group_by(ProductRisk.risk_level)
    ).all()
    counts = {level: 0 for level in LEVELS}
    counts.update({level: n for level, n in rows})
    total = sum(counts.values())

    avg_score = db.scalar(
        select(func.avg(ProductRisk.risk_score)).where(ProductRisk.upload_id == record.id)
    )

    # Per-category breakdown (feeds the bar chart)
    cat_rows = db.execute(
        select(
            ProductRisk.category,
            func.count().label("total"),
            func.sum(case((ProductRisk.risk_level == "Low", 1), else_=0)).label("low"),
            func.sum(case((ProductRisk.risk_level == "Medium", 1), else_=0)).label("medium"),
            func.sum(case((ProductRisk.risk_level == "High", 1), else_=0)).label("high"),
            func.avg(ProductRisk.risk_score).label("avg_score"),
        )
        .where(ProductRisk.upload_id == record.id)
        .group_by(ProductRisk.category)
        .order_by(func.avg(ProductRisk.risk_score).desc())
    ).all()

    return {
        "upload": _upload_info(record),
        "total_items": total,
        "risk_counts": counts,
        "risk_percentages": {level: _pct(counts[level], total) for level in LEVELS},
        "average_risk_score": round(float(avg_score or 0), 2),
        "high_risk_percentage": _pct(counts["High"], total),
        "categories": [
            {
                "category": c.category,
                "total": int(c.total),
                "low": int(c.low),
                "medium": int(c.medium),
                "high": int(c.high),
                "avg_score": round(float(c.avg_score), 2),
            }
            for c in cat_rows
        ],
    }


@router.get("/risks")
def list_risks(
    upload_id: Optional[int] = None,
    risk_level: Optional[Literal["Low", "Medium", "High"]] = Query(
        None, description="Filter by one level. If omitted, only Medium + High are returned."
    ),
    include_low: bool = Query(False, description="Also return Low-risk items (when risk_level is not set)."),
    category: Optional[str] = Query(None, description="Exact category name (case-insensitive)."),
    search: Optional[str] = Query(None, description="Text to look for in the product name."),
    sort_by: Literal["risk_score", "product_name", "category", "rating", "discount", "price"] = "risk_score",
    order: Literal["asc", "desc"] = "desc",
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """List of risky items (with reasoning), filterable, sortable and paginated."""
    record = _resolve_upload(db, upload_id)

    conditions = [ProductRisk.upload_id == record.id]
    if risk_level:
        conditions.append(ProductRisk.risk_level == risk_level)
    elif not include_low:
        conditions.append(ProductRisk.risk_level.in_(("Medium", "High")))
    if category:
        conditions.append(func.lower(ProductRisk.category) == category.strip().lower())
    if search:
        conditions.append(ProductRisk.product_name.ilike(f"%{search.strip()}%"))

    total = db.scalar(select(func.count()).select_from(ProductRisk).where(*conditions))

    sort_col = getattr(ProductRisk, sort_by)
    sort_expr = sort_col.desc() if order == "desc" else sort_col.asc()
    items = db.scalars(
        select(ProductRisk)
        .where(*conditions)
        .order_by(sort_expr, ProductRisk.id)
        .offset(skip)
        .limit(limit)
    ).all()

    return {
        "upload_id": record.id,
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [_item(r) for r in items],
    }


@router.get("/insights")
def risk_insights(upload_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Reasoning layer: what is driving the risk, in plain English."""
    record = _resolve_upload(db, upload_id)
    base = ProductRisk.upload_id == record.id

    # --- Risk drivers: how many items hit each factor ---
    low_rating = ProductRisk.rating < LOW_RATING_LIMIT
    heavy_discount = ProductRisk.discount >= HEAVY_DISCOUNT_LIMIT
    price_outlier = ProductRisk.reasoning.like("%category median%")
    discount_applied = ProductRisk.reasoning.like("%Discount was applied%")
    stat_outlier = ProductRisk.reasoning.like("%standard deviations%")

    f = db.execute(
        select(
            func.count().label("total"),
            func.sum(case((ProductRisk.risk_level == "High", 1), else_=0)).label("high"),
            func.sum(case((low_rating, 1), else_=0)).label("low_rating"),
            func.sum(case((heavy_discount, 1), else_=0)).label("heavy_discount"),
            func.sum(case((price_outlier, 1), else_=0)).label("price_outlier"),
            func.sum(case((discount_applied, 1), else_=0)).label("discount_applied"),
            func.sum(case((stat_outlier, 1), else_=0)).label("stat_outlier"),
            func.sum(case(((low_rating) & (heavy_discount), 1), else_=0)).label("combo"),
        ).where(base)
    ).one()

    total = int(f.total)
    high = int(f.high or 0)
    drivers = {
        "low_rating": int(f.low_rating or 0),
        "heavy_discount": int(f.heavy_discount or 0),
        "price_outlier": int(f.price_outlier or 0),
        "discount_applied": int(f.discount_applied or 0),
        "statistical_outlier": int(f.stat_outlier or 0),
    }
    combo = int(f.combo or 0)

    # --- Riskiest categories (by average score) ---
    cats = db.execute(
        select(
            ProductRisk.category,
            func.count().label("total"),
            func.avg(ProductRisk.risk_score).label("avg_score"),
            func.sum(case((ProductRisk.risk_level == "High", 1), else_=0)).label("high"),
        )
        .where(base)
        .group_by(ProductRisk.category)
        .order_by(func.avg(ProductRisk.risk_score).desc())
        .limit(3)
    ).all()
    riskiest_categories = [
        {
            "category": c.category,
            "avg_score": round(float(c.avg_score), 2),
            "high_risk_items": int(c.high),
            "total_items": int(c.total),
        }
        for c in cats
    ]

    # --- Top 5 highest-risk items with their explanations ---
    top = db.scalars(
        select(ProductRisk).where(base).order_by(ProductRisk.risk_score.desc(), ProductRisk.id).limit(5)
    ).all()

    # --- Plain-English headlines ---
    labels = {
        "low_rating": f"low customer ratings (below {LOW_RATING_LIMIT:g})",
        "heavy_discount": f"heavy discounting ({HEAVY_DISCOUNT_LIMIT:g}% or more)",
        "price_outlier": "prices far above their category median",
        "discount_applied": "discounts being applied",
        "statistical_outlier": "statistically unusual values",
    }
    headlines = [
        f"{high} of {total} items ({_pct(high, total)}%) are High risk."
    ]
    if any(drivers.values()):
        main = max(drivers, key=drivers.get)
        headlines.append(
            f"The most common risk driver is {labels[main]}, affecting {drivers[main]} item(s)."
        )
    if combo:
        headlines.append(
            f"{combo} item(s) combine low ratings with heavy discounts - the most urgent to review."
        )
    if riskiest_categories and riskiest_categories[0]["avg_score"] > 0:
        c = riskiest_categories[0]
        headlines.append(
            f"'{c['category']}' is the riskiest category (average score {c['avg_score']}, "
            f"{c['high_risk_items']} High-risk item(s))."
        )
    if high == 0:
        headlines.append("No High-risk items were found in this dataset.")

    # --- Rule-based recommendations ---
    recommendations = []
    if drivers["low_rating"]:
        recommendations.append("Investigate quality or listing issues behind the low-rated items.")
    if drivers["heavy_discount"]:
        recommendations.append("Review discount strategy: deep discounts may signal overstock or margin pressure.")
    if drivers["price_outlier"]:
        recommendations.append("Check whether the high-priced outliers are priced correctly for their category.")
    if drivers["discount_applied"]:
        recommendations.append("Check whether discounted purchases are eroding margin on the flagged items.")
    if drivers["statistical_outlier"]:
        recommendations.append("Verify the flagged outlier values: they may be data-entry errors or genuine exceptions worth investigating.")
    if not recommendations:
        recommendations.append("No action needed: all factors are within healthy ranges.")

    return {
        "upload_id": record.id,
        "headlines": headlines,
        "risk_drivers": drivers,
        "combined_low_rating_and_heavy_discount": combo,
        "riskiest_categories": riskiest_categories,
        "top_risks": [_item(r) for r in top],
        "recommendations": recommendations,
    }
