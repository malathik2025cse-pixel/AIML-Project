from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SafetyCheck(Base):
    __tablename__ = "safety_checks"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    consultation_id: Mapped[int] = mapped_column(
        ForeignKey("consultations.id"),
        nullable=False,
        index=True,
    )

    prescription_id: Mapped[int | None] = mapped_column(
        ForeignKey("prescriptions.id"),
        nullable=True,
        index=True,
    )

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    patient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="Pending Review",
    )

    doctor_decision: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    doctor_decision_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


class SafetyFinding(Base):
    __tablename__ = "safety_findings"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    safety_check_id: Mapped[int] = mapped_column(
        ForeignKey("safety_checks.id"),
        nullable=False,
        index=True,
    )

    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    severity: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    explanation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )