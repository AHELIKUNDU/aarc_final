"""
AARC Risk Engine
----------------
Works with (almost) any CSV:

  1. detect_columns() / preview_upload() - guess which columns mean what (name, category,
     rating, price, discount); the user can correct the guess in the UI
  2. ingest_csv()      - read (any delimiter / encoding), clean and standardise
  3. score_dataframe() - two transparent scoring modes:
        "rules"   : rating / discount / price rules (business-style data)
        "anomaly" : statistical outliers (z-scores) across ANY numeric columns
  4. process_upload()  - glue: ingest -> score -> save to the database

All rules and thresholds live in the CONFIG section so they are easy to tune.
"""
import csv
import io
import re

import numpy as np
import pandas as pd
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import ProductRisk, UploadRecord

# ============================== CONFIG ===================================

INSERT_CHUNK = 5000      # rows written to the database per batch
PREVIEW_ROWS = 2000      # rows read when previewing / detecting columns

# Risk level thresholds (on the 0-100 score)
HIGH_THRESHOLD = 50
MEDIUM_THRESHOLD = 25

# --- "rules" mode ---
# Rating rules: (rating is BELOW this value, points, label). Checked top-down.
RATING_RULES = [
    (2.0, 70, "very low"),
    (3.0, 55, "low"),
    (3.5, 25, "below average"),
    (4.0, 10, "slightly below target"),
]
# Discount rules: (discount % is AT LEAST this value, points, label). Checked top-down.
DISCOUNT_RULES = [
    (60, 35, "extreme"),
    (40, 25, "high"),
    (25, 10, "moderate"),
]
DISCOUNT_FLAG_POINTS = 10        # when the discount column is just Yes/No
PRICE_OUTLIER_RATIO = 3.0        # price >= this x category median -> extra points
PRICE_OUTLIER_POINTS = 10
MIN_CATEGORY_SIZE = 3            # need this many priced items to trust a median

# --- "anomaly" mode ---
# (|z-score| is AT LEAST this, points). Checked top-down, per numeric column.
ANOMALY_RULES = [(4.0, 40), (3.0, 25), (2.0, 10)]
MAX_FEATURE_COLUMNS = 12         # analyse at most this many numeric columns

# --- column detection ---
ROLES = ("product_name", "category", "rating", "price", "discount")
DETECTION_ORDER = ("rating", "discount", "price", "category", "product_name")

# Exact (normalised) header names
COLUMN_ALIASES = {
    "product_name": ["product_name", "product", "productname", "name", "item", "item_name",
                     "itemname", "item_purchased", "itempurchased", "title", "description", "sku"],
    "category": ["category", "product_category", "type", "department", "segment"],
    "rating": ["rating", "ratings", "score", "stars", "customer_rating", "item_rating",
               "itemrating", "review_score"],
    "price": ["price", "cost", "unit_price", "unitprice", "mrp", "amount", "revenue",
              "sales", "purchase_amount"],
    "discount": ["discount", "discount_percent", "discount_pct", "discount_percentage",
                 "discount_applied", "discountapplied"],
}
# Words that may appear anywhere in a header (second-pass guess)
KEYWORDS = {
    "rating": ["rating", "stars", "review", "score"],
    "discount": ["discount", "promo", "offer", "coupon"],
    "price": ["price", "amount", "cost", "revenue", "sales", "spend", "total", "value", "mrp", "fee"],
    "category": ["category", "type", "segment", "department", "class", "group", "genre"],
    "product_name": ["product", "item", "name", "title", "description", "sku"],
}
ALLOWED_KINDS = {
    "rating": {"numeric"},
    "discount": {"numeric", "flag"},
    "price": {"numeric"},
    "category": {"text"},
    "product_name": {"text"},
}

YES_VALUES = {"yes", "y", "true", "t", "1", "1.0"}
NO_VALUES = {"no", "n", "false", "f", "0", "0.0"}
FEATURE_PREFIX = "x__"


class DataValidationError(Exception):
    """Raised when the uploaded file cannot be used (bad format / missing columns)."""


# ========================= SMALL HELPERS =================================

def _normalize_header(col) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(col).strip().lower()).strip("_")


def _to_numeric(series: pd.Series) -> pd.Series:
    """Lenient: '$1,200', '30%', '4.5/5', 'N/A' -> floats / NaN."""
    cleaned = (
        series.astype(str)
        .str.split("/").str[0]
        .str.replace(r"[^0-9.\-]", "", regex=True)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _strict_numeric(series: pd.Series) -> pd.Series:
    """Strict: only plain numbers with optional currency / % / thousands commas."""
    cleaned = series.astype(str).str.strip().str.replace(r"[,$%₹€£]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def _is_flag(series: pd.Series) -> bool:
    values = series.dropna().astype(str).str.strip().str.lower().unique()
    return 0 < len(values) <= 4 and set(values) <= (YES_VALUES | NO_VALUES)


def _column_kind(series: pd.Series) -> str:
    """'flag' (Yes/No), 'numeric' or 'text'."""
    sample = series.dropna().head(PREVIEW_ROWS)
    if sample.empty:
        return "text"
    if _is_flag(sample):
        return "flag"
    if _strict_numeric(sample).notna().mean() >= 0.8:
        return "numeric"
    return "text"


def _looks_like_id(norm: str, series: pd.Series) -> bool:
    non_null = series.dropna()
    if len(non_null) < 5:
        return False
    unique_ratio = non_null.nunique() / len(non_null)
    return (norm == "id" or norm.endswith("id")) and unique_ratio >= 0.9


# ========================= READING + DETECTION ===========================

def _detect_delimiter(sample: bytes) -> str:
    text = sample.decode("utf-8", errors="ignore")
    if "\n" in text:
        text = text.rsplit("\n", 1)[0]
    try:
        return csv.Sniffer().sniff(text, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _read_csv(file_bytes: bytes, nrows=None) -> pd.DataFrame:
    head = file_bytes[:8192]
    sep = _detect_delimiter(head)
    decimal = "," if (sep == ";" and re.search(rb"\d,\d", head) and not re.search(rb"\d\.\d", head)) else "."
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(
                io.BytesIO(file_bytes), sep=sep, decimal=decimal, encoding=encoding, nrows=nrows,
                on_bad_lines="skip", low_memory=False,
            )
            break
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError:
            raise DataValidationError("The CSV file is empty.")
        except pd.errors.ParserError as exc:
            raise DataValidationError(f"Could not parse the CSV file: {exc}")
    else:
        raise DataValidationError("Could not decode the file. Please save it as UTF-8 CSV.")

    df.columns = [str(c).strip() for c in df.columns]
    if df.empty:
        raise DataValidationError("The CSV file has no data rows.")
    return df


def detect_columns(df: pd.DataFrame):
    """Guess which column plays which role. Returns (mapping, kinds)."""
    norm = {c: _normalize_header(c) for c in df.columns}
    kinds = {c: _column_kind(df[c]) for c in df.columns}
    mapping = {role: None for role in ROLES}
    used = set()

    for role in DETECTION_ORDER:
        pick = None
        # pass 1: exact header name
        for col in df.columns:
            if col not in used and norm[col] in COLUMN_ALIASES[role] and kinds[col] in ALLOWED_KINDS[role]:
                pick = col
                break
        # pass 2: header contains a keyword
        if pick is None:
            for col in df.columns:
                if col in used or kinds[col] not in ALLOWED_KINDS[role]:
                    continue
                if role == "product_name" and _looks_like_id(norm[col], df[col]):
                    continue
                if any(k in norm[col] for k in KEYWORDS[role]):
                    pick = col
                    break
        if pick is not None:
            mapping[role] = pick
            used.add(pick)

    # Fallbacks when headers give no clue: use what the data looks like
    if mapping["product_name"] is None:
        for col in df.columns:
            non_null = df[col].dropna()
            if (col not in used and kinds[col] == "text" and len(non_null) >= 5
                    and non_null.nunique() / len(non_null) >= 0.9):
                mapping["product_name"] = col
                used.add(col)
                break
    if mapping["category"] is None:
        col = _fallback_category(df, used)
        if col:
            mapping["category"] = col
    return mapping, kinds


def preview_upload(file_bytes: bytes) -> dict:
    """Light-weight look at the start of a file: columns, sample rows, detected mapping."""
    if b"\n" in file_bytes and not file_bytes.endswith(b"\n"):
        file_bytes = file_bytes.rsplit(b"\n", 1)[0]   # drop a possibly cut-off last line
    df = _read_csv(file_bytes, nrows=PREVIEW_ROWS)
    mapping, kinds = detect_columns(df)
    return {
        "columns": [
            {
                "name": col,
                "kind": kinds[col],
                "sample": df[col].dropna().astype(str).head(3).tolist(),
            }
            for col in df.columns
        ],
        "detected": mapping,
        "suggested_mode": "rules" if (mapping["rating"] or mapping["discount"]) else "anomaly",
        "preview_rows": df.head(5).fillna("").astype(str).to_dict("records"),
        "rows_in_sample": len(df),
    }


# ============================ INGESTION ==================================

def _validate_mapping(mapping: dict, df: pd.DataFrame) -> dict:
    roles = {}
    for role in ROLES:
        col = mapping.get(role)
        if col in (None, ""):
            roles[role] = None
        elif col not in df.columns:
            raise DataValidationError(f"Mapped column '{col}' was not found in the file.")
        else:
            roles[role] = col
    return roles


def _text_series(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().replace("", pd.NA)


def _fallback_names(df: pd.DataFrame) -> pd.Series:
    for col in df.columns:
        if _looks_like_id(_normalize_header(col), df[col]):
            return f"{col} " + df[col].astype(str)
    return "Row " + pd.Series(df.index + 2, index=df.index).astype(str)  # = line number in file


def _fallback_category(df: pd.DataFrame, used: set):
    for col in df.columns:
        if col in used:
            continue
        if _column_kind(df[col]) == "text" and 2 <= df[col].nunique() <= 30:
            if not _looks_like_id(_normalize_header(col), df[col]):
                return col
    return None


def _prepare_rating(series: pd.Series, notes: list) -> pd.Series:
    r = _to_numeric(series)
    r = r.where(~(r < 0))
    valid = r.dropna()
    if len(valid) and (valid > 5).mean() >= 0.15:   # many values above 5 -> a different scale
        top = valid.max()
        if top <= 10:
            r = r / 2
            notes.append("Rating looks like a 0-10 scale; converted to 0-5.")
        elif top <= 100:
            r = r / 20
            notes.append("Rating looks like a 0-100 scale; converted to 0-5.")
    bad = r > 5
    if bad.sum():
        r = r.where(~bad)
        notes.append(f"{int(bad.sum())} rating(s) outside the 0-5 range were treated as missing.")
    return r


def _prepare_discount(series: pd.Series, notes: list) -> pd.Series:
    d = _to_numeric(series)
    valid = d.dropna()
    if len(valid) and valid.max() <= 1 and (valid % 1 != 0).any():
        d = d * 100
        notes.append("Discount looks like a fraction (0-1); converted to a percentage.")
    bad = (d < 0) | (d > 100)
    if bad.sum():
        d = d.where(~bad)
        notes.append(f"{int(bad.sum())} discount(s) outside 0-100% were treated as missing.")
    return d


def _numeric_features(df: pd.DataFrame, exclude: set) -> list:
    """Numeric columns worth running outlier detection on."""
    features = []
    for col in df.columns:
        if col in exclude or _column_kind(df[col]) != "numeric":
            continue
        x = _strict_numeric(df[col]).dropna()
        if len(x) < 3 or x.nunique() < 3:
            continue
        if len(x) >= 10 and x.nunique() / len(x) >= 0.95 and (x % 1 == 0).all():
            continue   # looks like an ID / running index
        features.append(col)
        if len(features) >= MAX_FEATURE_COLUMNS:
            break
    return features


def ingest_csv(file_bytes: bytes, mapping: dict = None, mode: str = "auto"):
    """Read + clean a CSV. Returns (clean_dataframe, stats_dict)."""
    df = _read_csv(file_bytes)
    notes = []
    total_rows = len(df)

    # --- 1. Drop empty rows and exact duplicates ---
    before = len(df)
    df = df.dropna(how="all")
    if before - len(df):
        notes.append(f"Removed {before - len(df)} completely empty row(s).")
    before = len(df)
    df = df.drop_duplicates()
    if before - len(df):
        notes.append(f"Removed {before - len(df)} duplicate row(s).")
    if df.empty:
        raise DataValidationError("No usable rows remained after cleaning.")

    # --- 2. Which column is which? ---
    detected, kinds = detect_columns(df)
    roles = detected if mapping is None else _validate_mapping(mapping, df)

    has_rules_cols = bool(roles["rating"] or roles["discount"])
    if mode == "auto":
        mode = "rules" if has_rules_cols else "anomaly"
    elif mode == "rules" and not has_rules_cols:
        raise DataValidationError(
            "Rule-based scoring needs a rating or discount column. "
            "Map one, or choose Statistical mode."
        )
    elif mode not in ("rules", "anomaly"):
        raise DataValidationError(f"Unknown scoring mode '{mode}'.")

    # --- 3. Build the standard frame ---
    out = pd.DataFrame(index=df.index)

    # name
    if roles["product_name"]:
        out["product_name"] = _text_series(df[roles["product_name"]])
    else:
        out["product_name"] = _fallback_names(df)
        notes.append("No name column mapped; rows are labelled by ID or row number.")

    # category
    if roles["category"]:
        out["category"] = _text_series(df[roles["category"]]).fillna("Uncategorized").astype(str).str.title()
    else:
        out["category"] = "All Records"

    # rating / price / discount
    out["rating"] = _prepare_rating(df[roles["rating"]], notes) if roles["rating"] else float("nan")

    if roles["price"]:
        price = _to_numeric(df[roles["price"]])
        bad = price < 0
        if bad.sum():
            price = price.where(~bad)
            notes.append(f"{int(bad.sum())} negative price(s) were treated as missing.")
        out["price"] = price
    else:
        out["price"] = float("nan")

    out["discount"] = float("nan")
    out["discount_flag"] = pd.Series(pd.NA, index=df.index, dtype="object")
    discount_is_flag = False
    if roles["discount"]:
        if kinds[roles["discount"]] == "flag":
            discount_is_flag = True
            lookup = {**{v: True for v in YES_VALUES}, **{v: False for v in NO_VALUES}}
            out["discount_flag"] = df[roles["discount"]].astype(str).str.strip().str.lower().map(lookup).astype("object")
            notes.append(
                f"'{roles['discount']}' is a Yes/No flag: a discount adds {DISCOUNT_FLAG_POINTS} risk points."
            )
        else:
            out["discount"] = _prepare_discount(df[roles["discount"]], notes)

    # --- 4. Rows without a name (only when a name column was mapped) ---
    if roles["product_name"]:
        keep = out["product_name"].notna()
        if (~keep).sum():
            notes.append(f"Removed {int((~keep).sum())} row(s) with no product name.")
            out, df = out[keep], df[keep]
    out["product_name"] = out["product_name"].astype(str)

    # --- 5. Numeric feature columns for statistical mode ---
    if mode == "anomaly":
        exclude = {roles["product_name"], roles["category"]} - {None}
        features = _numeric_features(df, exclude)
        if not features:
            raise DataValidationError(
                "No numeric columns with enough variation were found to analyse."
            )
        for col in features:
            out[FEATURE_PREFIX + col] = _strict_numeric(df[col])
        notes.append(f"Statistical mode analysed {len(features)} numeric column(s): {', '.join(features)}.")

    # --- 6. Missing-value report (we never invent values) ---
    for col, role in (("rating", "rating"), ("discount", "discount"), ("price", "price")):
        if roles[role] and not (role == "discount" and discount_is_flag):
            missing = int(out[col].isna().sum())
            if missing:
                notes.append(f"{missing} row(s) have no {col}; that factor is skipped for them.")

    out = out.reset_index(drop=True)
    if out.empty:
        raise DataValidationError("No usable rows remained after cleaning.")

    stats = {
        "total_rows": total_rows,
        "processed_rows": len(out),
        "dropped_rows": total_rows - len(out),
        "cleaning_notes": notes,
        "mode": mode,
        "mapping": roles,
    }
    return out, stats


# ============================ RISK SCORING ===============================

def _risk_level(score: float) -> str:
    if score >= HIGH_THRESHOLD:
        return "High"
    if score >= MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


def _score_row(row: dict, ctx: dict) -> tuple:
    """Rules mode: (score 0-100, level, reasoning) for one record."""
    score = 0
    reasons = []

    # Rule 1: customer rating
    rating = row["rating"]
    if pd.isna(rating):
        if ctx["rating"]:
            reasons.append("Rating missing - rating factor not scored.")
    else:
        for limit, points, label in RATING_RULES:
            if rating < limit:
                score += points
                reasons.append(f"Rating {rating:.1f}/5 is {label} (below {limit}) (+{points}).")
                break

    # Rule 2: discount depth (percentage) ...
    discount = row["discount"]
    if pd.isna(discount):
        if ctx["discount"]:
            reasons.append("Discount missing - discount factor not scored.")
    else:
        for limit, points, label in DISCOUNT_RULES:
            if discount >= limit:
                score += points
                reasons.append(f"Discount of {discount:.0f}% is {label} (>= {limit}%) (+{points}).")
                break

    # ... or a Yes/No discount flag
    if ctx["flag"]:
        flag = row["discount_flag"]
        if isinstance(flag, (bool, np.bool_)):
            if flag:
                score += DISCOUNT_FLAG_POINTS
                reasons.append(f"Discount was applied (+{DISCOUNT_FLAG_POINTS}).")
        else:
            reasons.append("Discount info missing - discount factor not scored.")

    # Rule 3: price outlier within its category
    price, cat_median, cat_count = row["price"], row["cat_median_price"], row["cat_price_count"]
    if (
        not pd.isna(price) and not pd.isna(cat_median) and cat_median > 0
        and cat_count >= MIN_CATEGORY_SIZE and price >= PRICE_OUTLIER_RATIO * cat_median
    ):
        score += PRICE_OUTLIER_POINTS
        reasons.append(
            f"Price {price:,.2f} is {price / cat_median:.1f}x the category median "
            f"({cat_median:,.2f}) (+{PRICE_OUTLIER_POINTS})."
        )

    score = min(score, 100)
    if score == 0:
        reasons = [r for r in reasons if "missing" in r] + [
            "No risk factors triggered: rating, discount and price look healthy."
        ]
    return float(score), _risk_level(score), " ".join(reasons)


def _score_rules(df: pd.DataFrame):
    grouped = df.groupby("category")["price"]
    df = df.assign(
        cat_median_price=grouped.transform("median"),
        cat_price_count=grouped.transform("count"),
    )
    ctx = {
        "rating": bool(df["rating"].notna().any()),
        "discount": bool(df["discount"].notna().any()),
        "flag": bool(df["discount_flag"].notna().any()),
    }
    results = [_score_row(row, ctx) for row in df.to_dict("records")]
    return [r[0] for r in results], [r[1] for r in results], [r[2] for r in results]


def _score_anomaly(df: pd.DataFrame):
    """Statistical mode: z-score outliers across every numeric feature column."""
    feature_cols = [c for c in df.columns if c.startswith(FEATURE_PREFIX)]
    n = len(df)
    score = np.zeros(n)
    reasons = [[] for _ in range(n)]

    for col in feature_cols:
        x = df[col].to_numpy(dtype=float)
        if np.isnan(x).all():
            continue
        mean, std = np.nanmean(x), np.nanstd(x)
        if not std or np.isnan(std):
            continue
        z = (x - mean) / std
        absz = np.abs(z)
        points = np.select([absz >= t for t, _ in ANOMALY_RULES], [p for _, p in ANOMALY_RULES], default=0)
        label = col[len(FEATURE_PREFIX):]
        for i in np.nonzero(points)[0]:
            direction = "above" if z[i] > 0 else "below"
            reasons[i].append(
                f"{label} {x[i]:,.2f} is {absz[i]:.1f} standard deviations {direction} "
                f"the average ({mean:,.2f}) (+{int(points[i])})."
            )
        score += points

    score = np.minimum(score, 100)
    none_text = f"No unusual values detected across {len(feature_cols)} numeric column(s)."
    return (
        [float(s) for s in score],
        [_risk_level(s) for s in score],
        [" ".join(r) if r else none_text for r in reasons],
    )


def score_dataframe(df: pd.DataFrame, mode: str = "rules") -> pd.DataFrame:
    """Adds risk_score, risk_level and reasoning columns."""
    scores, levels, reasons = _score_anomaly(df) if mode == "anomaly" else _score_rules(df)
    df = df.copy()
    df["risk_score"], df["risk_level"], df["reasoning"] = scores, levels, reasons
    helper = ["discount_flag"] + [c for c in df.columns if c.startswith(FEATURE_PREFIX)]
    return df.drop(columns=helper)


# ============================ SAVE TO DB =================================

def _py(value):
    """NaN / pandas NA -> None, otherwise a plain Python float (safe for SQLite)."""
    return None if pd.isna(value) else float(value)


def process_upload(db: Session, filename: str, file_bytes: bytes, mapping: dict = None, mode: str = "auto") -> dict:
    """Ingest -> score -> store. Returns a summary dict for the API response."""
    record = UploadRecord(filename=filename, status="pending")
    db.add(record)
    db.commit()
    db.refresh(record)
    upload_id = record.id

    try:
        clean_df, stats = ingest_csv(file_bytes, mapping, mode)
        scored = score_dataframe(clean_df, stats["mode"])

        records = [
            {
                "upload_id": upload_id,
                "product_name": row.product_name,
                "category": row.category,
                "rating": _py(row.rating),
                "price": _py(row.price),
                "discount": _py(row.discount),
                "risk_score": row.risk_score,
                "risk_level": row.risk_level,
                "reasoning": row.reasoning,
            }
            for row in scored.itertuples(index=False)
        ]
        # Bulk insert in chunks: far faster than adding one ORM object per row
        for start in range(0, len(records), INSERT_CHUNK):
            db.execute(insert(ProductRisk), records[start:start + INSERT_CHUNK])

        record.total_rows = stats["total_rows"]
        record.processed_rows = stats["processed_rows"]
        record.status = "processed"
        db.commit()
    except Exception:
        db.rollback()
        failed = db.get(UploadRecord, upload_id)
        failed.status = "failed"
        db.commit()
        raise

    counts = scored["risk_level"].value_counts()
    return {
        "upload_id": upload_id,
        "filename": filename,
        "status": "processed",
        "mode": stats["mode"],
        "mapping": stats["mapping"],
        "rows": {
            "total": stats["total_rows"],
            "processed": stats["processed_rows"],
            "dropped": stats["dropped_rows"],
        },
        "risk_summary": {lvl: int(counts.get(lvl, 0)) for lvl in ("Low", "Medium", "High")},
        "average_risk_score": round(float(scored["risk_score"].mean()), 2),
        "cleaning_notes": stats["cleaning_notes"],
    }
