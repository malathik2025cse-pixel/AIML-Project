from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MedicationReference(Base):
    __tablename__ = "medication_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    rxcui: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    synonym: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    term_type: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    source: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    last_verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )