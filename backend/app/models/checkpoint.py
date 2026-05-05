from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db import Base


class CheckpointQuestion(Base):
    __tablename__ = "checkpoint_questions"

    id = Column(Integer, primary_key=True, index=True)
    module = Column(String(50), nullable=False, index=True)
    layer = Column(Integer, nullable=False)
    question_type = Column(String(20), nullable=False)  # mc | short_answer
    question_text = Column(Text, nullable=False)
    choices = Column(JSON, nullable=True)  # [{id, text, is_correct}]
    correct_answer = Column(Text, nullable=True)
    explanation = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    responses = relationship("CheckpointResponse", back_populates="question", cascade="all, delete-orphan")


class CheckpointResponse(Base):
    __tablename__ = "checkpoint_responses"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("checkpoint_questions.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(String(255), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("module_sessions.id"), nullable=True)
    selected_choice = Column(String(10), nullable=True)
    text_response = Column(Text, nullable=True)
    is_correct = Column(Boolean, nullable=True)
    answered_at = Column(DateTime(timezone=True), server_default=func.now())

    question = relationship("CheckpointQuestion", back_populates="responses")
    user = relationship("User", back_populates="checkpoint_responses")
    session = relationship("ModuleSession", back_populates="checkpoint_responses")
