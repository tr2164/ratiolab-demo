from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import relationship
from app.db import Base


class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    name = Column(String(255), nullable=False)
    driver_overrides = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    model = relationship("Model", back_populates="scenarios")
