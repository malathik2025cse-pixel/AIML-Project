from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.services.admin_service import approve_user, reject_user


def get_admin_by_email(
    db: Session,
    email: str,
) -> User | None:
    """
    Find the single Admin account by email.
    """

    return db.scalar(
        select(User).where(
            User.email == email,
            User.role == "Admin",
        )
    )


def get_admin(
    db: Session,
) -> User | None:
    """
    Return the single Admin account.

    There must never be more than one Admin.
    """

    return db.scalar(
        select(User).where(
            User.role == "Admin",
        )
    )


def get_pending_users(
    db: Session,
) -> list[User]:
    """
    Return Patient and Doctor registrations
    waiting for Admin review.
    """

    return list(
        db.scalars(
            select(User)
            .where(
                User.role.in_(["Patient", "Doctor"]),
                User.status == "Pending Approval",
            )
            .order_by(User.id.asc())
        ).all()
    )


def get_all_users(
    db: Session,
) -> list[User]:
    """
    Return Patient and Doctor accounts.

    Admin management will use this later for:
    - viewing accounts
    - activating/deactivating accounts
    - reviewing statuses
    """

    return list(
        db.scalars(
            select(User)
            .where(
                User.role.in_(["Patient", "Doctor"])
            )
            .order_by(User.id.asc())
        ).all()
    )


def approve_registration(
    db: Session,
    user_id: int,
) -> User | None:
    """
    Approve a Patient or Doctor registration.

    Unique ID generation and activation are handled
    by the existing admin_service.
    """

    return approve_user(
        db=db,
        user_id=user_id,
    )


def reject_registration(
    db: Session,
    user_id: int,
) -> User | None:
    """
    Reject a Patient or Doctor registration.
    """

    return reject_user(
        db=db,
        user_id=user_id,
    )