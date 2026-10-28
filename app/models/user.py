from sqlalchemy import Boolean, Integer, String, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    # Public MedShield ID shown after approval.
    # Examples:
    # MS-P-00001
    # MS-D-00001
    unique_user_id: Mapped[str | None] = mapped_column(
        String(30),
        unique=True,
        index=True,
        nullable=True,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="Pending Approval",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Doctor verification information
    medical_registration_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    registration_authority: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    qualification: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    specialization: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    years_of_practice: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    hospital_clinic: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # PostgreSQL-level protection:
    # only one row can have role = "Admin".
    __table_args__ = (
        Index(
            "ix_users_single_admin",
            "role",
            unique=True,
            postgresql_where=(role == "Admin"),
        ),
    )