from sqlalchemy import Column, Integer, String, DateTime, func
from sqlalchemy.orm import relationship
from app.db import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), unique=True, nullable=False, index=True)
    name = Column(String(255))
    cik = Column(String(20))
    sector = Column(String(100))
    industry = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    financial_data = relationship("FinancialData", back_populates="company", cascade="all, delete-orphan")
    models = relationship("Model", back_populates="company", cascade="all, delete-orphan")
    news_articles = relationship("NewsArticle", back_populates="company", cascade="all, delete-orphan")
