from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def create_audit_log(
    db: Session,
    actor_user_id: int | None,
    actor_role: str | None,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    description: str | None = None,
):
    audit_log = AuditLog(
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        description=description,
    )

    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)

    return audit_log