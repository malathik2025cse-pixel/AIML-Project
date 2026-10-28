from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User


def generate_unique_user_id(db: Session, role: str) -> str:
    if role == "Patient":
        prefix = "MS-P-"
    elif role == "Doctor":
        prefix = "MS-D-"
    else:
        raise ValueError("Unique ID can only be generated for Patient or Doctor")

    existing_ids = db.scalars(
        select(User.unique_user_id)
        .where(User.role == role)
        .where(User.unique_user_id.is_not(None))
    ).all()

    numbers = []

    for value in existing_ids:
        if value and value.startswith(prefix):
            try:
                numbers.append(int(value.replace(prefix, "")))
            except ValueError:
                continue

    next_number = max(numbers, default=0) + 1

    return f"{prefix}{next_number:05d}"


def approve_user(db: Session, user_id: int) -> User | None:
    user = db.scalar(
        select(User).where(User.id == user_id)
    )

    if user is None:
        return None

    if user.role not in {"Patient", "Doctor"}:
        return None

    if user.status != "Pending Approval":
        return None

    user.unique_user_id = generate_unique_user_id(
        db=db,
        role=user.role,
    )

    user.status = "Active"
    user.is_active = True

    db.commit()
    db.refresh(user)

    return user


def reject_user(db: Session, user_id: int) -> User | None:
    user = db.scalar(
        select(User).where(User.id == user_id)
    )

    if user is None:
        return None

    if user.role not in {"Patient", "Doctor"}:
        return None

    if user.status != "Pending Approval":
        return None

    user.status = "Rejected"
    user.is_active = False

    db.commit()
    db.refresh(user)

    return user