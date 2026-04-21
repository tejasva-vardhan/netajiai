from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base


class State(Base):
    __tablename__ = "states"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False, unique=True, index=True)

    cities = relationship("City", back_populates="state")


class City(Base):
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False, index=True)
    state_id = Column(Integer, ForeignKey("states.id", ondelete="CASCADE"), nullable=False)

    state = relationship("State", back_populates="cities")
    officer_mappings = relationship("OfficerMapping", back_populates="city")
    complaints = relationship("Complaint", back_populates="city")


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    keyword = Column(String(64), nullable=False, unique=True, index=True)

    officer_mappings = relationship("OfficerMapping", back_populates="department")


class OfficerMapping(Base):
    __tablename__ = "officer_mappings"
    __table_args__ = (
        UniqueConstraint("city_id", "department_id", name="uq_city_department"),
    )

    id = Column(Integer, primary_key=True, index=True)
    city_id = Column(Integer, ForeignKey("cities.id", ondelete="CASCADE"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    level_1_email = Column(String(255), nullable=True)
    level_2_email = Column(String(255), nullable=True)
    level_3_email = Column(String(255), nullable=True)

    city = relationship("City", back_populates="officer_mappings")
    department = relationship("Department", back_populates="officer_mappings")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    # Legacy fields kept for backward compatibility with existing chat flow.
    user_id = Column(String(64), unique=True, nullable=True, index=True)
    phone = Column(String(20), nullable=True, index=True)
    # New citizen account fields (email OTP auth).
    email = Column(String(255), unique=True, nullable=True, index=True)
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    complaints = relationship(
        "Complaint",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(String(64), unique=True, nullable=False, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )

    city_id = Column(
        Integer,
        ForeignKey("cities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    issue_type = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String(255), nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    photo_path = Column(String(512), nullable=True)

    department = Column(String(255), nullable=True, index=True)
    status = Column(String(50), nullable=False, default="submitted", index=True)
    severity = Column(String(50), nullable=False, default="normal", index=True)
    escalation_level = Column(Integer, nullable=False, default=1)

    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    user = relationship("User", back_populates="complaints")
    city = relationship("City", back_populates="complaints")


class OTPCode(Base):
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    otp_hash = Column(String(255), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
