"""Central schema only; independent from the local pharmacy SQLite schema."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "license_customers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class License(Base):
    __tablename__ = "licenses"
    __table_args__ = (CheckConstraint("max_devices > 0"), CheckConstraint("status IN ('ACTIVE', 'DISABLED')"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("license_customers.id"), index=True)
    activation_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_devices: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (CheckConstraint("status IN ('AUTHORIZED', 'PENDING', 'REVOKED', 'LIMIT_REACHED')"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    license_id: Mapped[str | None] = mapped_column(ForeignKey("licenses.id"), nullable=True, index=True)
    app_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_activation: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class Alert(Base):
    __tablename__ = "new_device_alerts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Administrator(Base):
    __tablename__ = "administrators"
    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="DEVELOPER")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(ForeignKey("administrators.username"))
    csrf_hash: Mapped[str] = mapped_column(String(64))
    # CSRF is not an authentication token; keep it so the dashboard can recover after refresh.
    csrf_value: Mapped[str] = mapped_column(String(80))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RateLimit(Base):
    __tablename__ = "license_rate_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(Integer, default=0)


class Audit(Base):
    __tablename__ = "license_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    device_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
