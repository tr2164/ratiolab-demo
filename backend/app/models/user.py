from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    lti_sub = Column(String(255), unique=True, index=True, nullable=True)
    email = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=False)
    avatar_url = Column(String(500), nullable=True)
    is_demo = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    lti_sessions = relationship("LTISession", back_populates="user", cascade="all, delete-orphan")
    module_sessions = relationship("ModuleSession", back_populates="user", cascade="all, delete-orphan")
    checkpoint_responses = relationship("CheckpointResponse", back_populates="user", cascade="all, delete-orphan")


class LTISession(Base):
    __tablename__ = "lti_sessions"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    course_id = Column(String(255), nullable=False, index=True)
    course_title = Column(String(500), nullable=True)
    role = Column(String(50), nullable=False, default="student")
    deployment_id = Column(String(255), nullable=True)
    nrps_url = Column(String(1000), nullable=True)
    ags_url = Column(String(1000), nullable=True)
    launched_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User", back_populates="lti_sessions")
