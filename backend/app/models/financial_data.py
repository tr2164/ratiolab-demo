from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db import Base


class FinancialData(Base):
    __tablename__ = "financial_data"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    account_name = Column(String(500), nullable=False)
    xbrl_tag = Column(String(255))
    year = Column(Integer, nullable=False)
    amount = Column(Float)
    statement_type = Column(String(5), nullable=False)  # IS, BS, CF
    join_key = Column(String(500))
    source_api = Column(String(50))
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="financial_data")
