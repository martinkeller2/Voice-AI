import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Enum, ForeignKey,
    Integer, String, Text, Time, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database.connection import Base


class ApplianceType(str, enum.Enum):
    WASHER = "washer"
    DRYER = "dryer"
    REFRIGERATOR = "refrigerator"
    DISHWASHER = "dishwasher"
    OVEN = "oven"
    MICROWAVE = "microwave"
    FREEZER = "freezer"


class Technician(Base):
    __tablename__ = "technicians"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    phone = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

    service_areas = relationship("ServiceArea", back_populates="technician", cascade="all, delete-orphan")
    specialties = relationship("Specialty", back_populates="technician", cascade="all, delete-orphan")
    availability_slots = relationship("AvailabilitySlot", back_populates="technician", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="technician")


class ServiceArea(Base):
    __tablename__ = "service_areas"
    __table_args__ = (UniqueConstraint("technician_id", "zip_code"),)

    id = Column(Integer, primary_key=True, index=True)
    technician_id = Column(Integer, ForeignKey("technicians.id", ondelete="CASCADE"), nullable=False)
    zip_code = Column(String(10), nullable=False, index=True)

    technician = relationship("Technician", back_populates="service_areas")


class Specialty(Base):
    __tablename__ = "specialties"
    __table_args__ = (UniqueConstraint("technician_id", "appliance_type"),)

    id = Column(Integer, primary_key=True, index=True)
    technician_id = Column(Integer, ForeignKey("technicians.id", ondelete="CASCADE"), nullable=False)
    appliance_type = Column(Enum(ApplianceType, values_callable=lambda x: [e.value for e in x]), nullable=False)

    technician = relationship("Technician", back_populates="specialties")


class AvailabilitySlot(Base):
    __tablename__ = "availability_slots"

    id = Column(Integer, primary_key=True, index=True)
    technician_id = Column(Integer, ForeignKey("technicians.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_booked = Column(Boolean, default=False, nullable=False)

    technician = relationship("Technician", back_populates="availability_slots")
    appointment = relationship("Appointment", back_populates="slot", uselist=False)


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=False)
    slot_id = Column(Integer, ForeignKey("availability_slots.id"), unique=True, nullable=False)
    customer_name = Column(String(100), nullable=False)
    customer_phone = Column(String(20))
    customer_zip = Column(String(10))
    appliance_type = Column(Enum(ApplianceType, values_callable=lambda x: [e.value for e in x]))
    issue_description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    technician = relationship("Technician", back_populates="appointments")
    slot = relationship("AvailabilitySlot", back_populates="appointment")
