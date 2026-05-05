from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, UniqueConstraint
from app.db import Base


class DataMap(Base):
    __tablename__ = "data_maps"
    __table_args__ = (
        UniqueConstraint("company_id", "raw_account_name", "model_line", name="uq_company_account_line"),
    )

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    raw_account_name = Column(String(500), nullable=False)
    xbrl_tag = Column(String(255))
    model_line = Column(String(255), nullable=False)
    statement_type = Column(String(5), nullable=False)
    sign_flip = Column(Integer, default=1)
    sort_order = Column(Integer, default=0)
    confidence = Column(Float, default=1.0)
    mapping_method = Column(String(50))  # xbrl_rule, fmp_rule, llm, manual
    is_verified = Column(Boolean, default=False)
