"""SQLAlchemy ORM models for AARC."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class UploadRecord(Base):
    """One row per uploaded CSV file."""

    __tablename__ = "upload_records"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    uploaded_at = Column(DateTime, default=utcnow, nullable=False)
    total_rows = Column(Integer, default=0)        # rows in the raw file
    processed_rows = Column(Integer, default=0)    # rows kept after cleaning
    status = Column(String(20), default="pending") # pending | processed | failed

    risks = relationship(
        "ProductRisk",
        back_populates="upload",
        cascade="all, delete-orphan",
    )


class ProductRisk(Base):
    """Risk result for a single item (row) from an uploaded CSV."""

    __tablename__ = "product_risks"

    id = Column(Integer, primary_key=True, index=True)
    upload_id = Column(Integer, ForeignKey("upload_records.id"), nullable=False, index=True)

    product_name = Column(String(255), nullable=False)
    category = Column(String(100), default="Uncategorized", index=True)
    rating = Column(Float, nullable=True)
    price = Column(Float, nullable=True)
    discount = Column(Float, nullable=True)        # percentage, 0-100

    risk_score = Column(Float, default=0.0)        # 0-100
    risk_level = Column(String(10), default="Low", index=True)  # Low | Medium | High
    reasoning = Column(Text, default="")           # human-readable explanation

    upload = relationship("UploadRecord", back_populates="risks")
