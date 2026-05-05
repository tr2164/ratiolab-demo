from sqlalchemy import Column, Integer, String, Float, Text, Boolean, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db import Base


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(String(255), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    title = Column(String(500), nullable=False)
    module_focus = Column(String(50), nullable=True)
    questions = Column(JSON, default=list)
    grading_config = Column(JSON, default=dict)
    grading_rubric = Column(JSON, nullable=True)
    status = Column(String(30), default="draft")
    brightspace_csv = Column(Text, nullable=True)
    conversation_log = Column(JSON, default=list)
    lti_line_item_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    submissions = relationship("StudentSubmission", back_populates="assessment", cascade="all, delete-orphan")


class StudentSubmission(Base):
    __tablename__ = "student_submissions"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    answers = Column(JSON, default=list)
    ai_grades = Column(JSON, nullable=True)
    validator_grades = Column(JSON, nullable=True)
    final_score = Column(Float, nullable=True)
    max_score = Column(Float, nullable=True)
    instructor_approved = Column(Boolean, default=False)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    graded_at = Column(DateTime(timezone=True), nullable=True)
    grade_synced_at = Column(DateTime(timezone=True), nullable=True)

    assessment = relationship("Assessment", back_populates="submissions")
