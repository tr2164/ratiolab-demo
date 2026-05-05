from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import relationship
from app.db import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    title = Column(String(500), nullable=False)
    source = Column(String(255))
    url = Column(String(1000))
    published_at = Column(DateTime(timezone=True))
    snippet = Column(Text)
    content_hash = Column(String(64))
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="news_articles")
    sentiment = relationship("NewsSentiment", back_populates="article", uselist=False, cascade="all, delete-orphan")


class NewsSentiment(Base):
    __tablename__ = "news_sentiment"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, ForeignKey("news_articles.id"), nullable=False)
    overall_score = Column(Float)
    driver_impacts = Column(JSON)
    summary = Column(Text)
    analyzed_at = Column(DateTime(timezone=True), server_default=func.now())

    article = relationship("NewsArticle", back_populates="sentiment")
