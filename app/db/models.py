"""
Hikvision AI CCTV Platform — SQLAlchemy ORM Models
Maps to PostgreSQL tables created by init-db.sql.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    ARRAY,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    recorder_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="hikvision_nvr"
    )
    recorder_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    channel_number: Mapped[int] = mapped_column(Integer, nullable=False)
    rtsp_main_url: Mapped[str] = mapped_column(Text, nullable=False)
    rtsp_sub_url: Mapped[str] = mapped_column(Text, nullable=False)
    isapi_stream_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    snapshot_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    events: Mapped[List["Event"]] = relationship(back_populates="camera", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Camera {self.name} ch:{self.channel_number} @ {self.recorder_ip}>"


class Face(Base):
    __tablename__ = "faces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    embedding = Column(Vector(512), nullable=False)
    sample_image_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    detections: Mapped[List["FaceDetection"]] = relationship(back_populates="matched_face")

    def __repr__(self) -> str:
        return f"<Face {self.name} [{self.category}]>"


class LicensePlate(Base):
    __tablename__ = "license_plates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    plate_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    owner_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="registered")
    vehicle_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    detections: Mapped[List["PlateDetection"]] = relationship(back_populates="matched_plate")

    def __repr__(self) -> str:
        return f"<LicensePlate {self.plate_number} [{self.category}]>"


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    camera_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=True
    )
    event_source: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, default="detection")
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    bounding_box = Column(ARRAY(Integer), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    snapshot_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    clip_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json = Column("metadata", JSONB, default={})

    # Relationships
    camera: Mapped[Optional["Camera"]] = relationship(back_populates="events")
    face_detections: Mapped[List["FaceDetection"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    plate_detections: Mapped[List["PlateDetection"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    embeddings: Mapped[List["EventEmbedding"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    alerts: Mapped[List["AlertLog"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Event {self.event_source}:{self.target_type} @ {self.timestamp}>"


class FaceDetection(Base):
    __tablename__ = "face_detections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE")
    )
    matched_face_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("faces.id", ondelete="SET NULL"), nullable=True
    )
    similarity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bounding_box = Column(ARRAY(Integer), nullable=True)
    crop_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding = Column(Vector(512), nullable=True)
    is_unknown: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    event: Mapped["Event"] = relationship(back_populates="face_detections")
    matched_face: Mapped[Optional["Face"]] = relationship(back_populates="detections")


class PlateDetection(Base):
    __tablename__ = "plate_detections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE")
    )
    matched_plate_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("license_plates.id", ondelete="SET NULL"), nullable=True
    )
    detected_text: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bounding_box = Column(ARRAY(Integer), nullable=True)
    crop_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    event: Mapped["Event"] = relationship(back_populates="plate_detections")
    matched_plate: Mapped[Optional["LicensePlate"]] = relationship(back_populates="detections")


class EventEmbedding(Base):
    __tablename__ = "event_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE")
    )
    embedding = Column(Vector(512), nullable=False)
    description_caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    event: Mapped["Event"] = relationship(back_populates="embeddings")


class AlertLog(Base):
    __tablename__ = "alert_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE")
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False, default="telegram")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="sent")
    message_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    event: Mapped["Event"] = relationship(back_populates="alerts")
