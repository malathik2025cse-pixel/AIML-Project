from sqlalchemy import String, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MedicalRecord(Base):

    __tablename__ = "medical_records"


    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )


    patient_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )


    blood_group: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )


    allergies: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


    medical_conditions: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


    current_medications: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )