from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.consent import ConsentRequest
from app.models.user import User
from app.services.audit_service import create_audit_log


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def create_consent_request(
    db: Session,
    doctor: User,
    patient: User,
) -> ConsentRequest:
    existing_request = db.scalar(
        select(ConsentRequest)
        .where(ConsentRequest.doctor_id == doctor.id)
        .where(ConsentRequest.patient_id == patient.id)
        .where(ConsentRequest.status.in_(["Pending", "Active"]))
        .order_by(ConsentRequest.requested_at.desc())
    )

    if existing_request is not None:
        if existing_request.status == "Pending":
            return existing_request
        expire_consent_if_needed(db, existing_request)
        if existing_request.status == "Active":
            return existing_request

    consent = ConsentRequest(
        doctor_id=doctor.id,
        patient_id=patient.id,
        status="Pending",
    )

    db.add(consent)
    db.commit()
    db.refresh(consent)

    return consent


def get_patient_consent_requests(
    db: Session,
    patient: User,
) -> list[ConsentRequest]:
    requests = list(
        db.scalars(
            select(ConsentRequest)
            .where(ConsentRequest.patient_id == patient.id)
            .order_by(ConsentRequest.requested_at.desc())
        ).all()
    )
    return [expire_consent_if_needed(db, request) for request in requests]


def get_doctor_consent_requests(
    db: Session,
    doctor: User,
) -> list[ConsentRequest]:
    requests = list(
        db.scalars(
            select(ConsentRequest)
            .where(ConsentRequest.doctor_id == doctor.id)
            .order_by(ConsentRequest.requested_at.desc())
        ).all()
    )
    return [expire_consent_if_needed(db, request) for request in requests]


def approve_consent_request(
    db: Session,
    consent_id: int,
    patient: User,
    duration_minutes: int = 30,
) -> ConsentRequest | None:
    consent = db.scalar(
        select(ConsentRequest)
        .where(ConsentRequest.id == consent_id)
        .where(ConsentRequest.patient_id == patient.id)
    )

    if consent is None:
        return None

    if consent.status != "Pending":
        return None

    now = datetime.now(timezone.utc)

    consent.status = "Active"
    consent.responded_at = now
    consent.expires_at = now + timedelta(minutes=duration_minutes)

    db.commit()
    db.refresh(consent)

    return consent


def reject_consent_request(
    db: Session,
    consent_id: int,
    patient: User,
) -> ConsentRequest | None:
    consent = db.scalar(
        select(ConsentRequest)
        .where(ConsentRequest.id == consent_id)
        .where(ConsentRequest.patient_id == patient.id)
    )

    if consent is None:
        return None

    if consent.status != "Pending":
        return None

    consent.status = "Rejected"
    consent.responded_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(consent)

    return consent


def revoke_consent(
    db: Session,
    consent_id: int,
    doctor: User,
) -> ConsentRequest | None:
    consent = db.scalar(
        select(ConsentRequest)
        .where(ConsentRequest.id == consent_id)
        .where(ConsentRequest.doctor_id == doctor.id)
    )

    if consent is None:
        return None

    if consent.status == "Active" and not is_consent_active(consent):
        expire_consent_if_needed(db, consent)
        return None

    if consent.status != "Active":
        return None

    consent.status = "Revoked"
    consent.revoked_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(consent)

    create_audit_log(
        db=db,
        actor_user_id=doctor.id,
        actor_role=doctor.role,
        action="CONSENT_REVOKED",
        target_type="ConsentRequest",
        target_id=consent.id,
        description=(
            f"Doctor revoked consent request {consent.id} "
            f"for patient {consent.patient_id}."
        ),
    )

    return consent


def revoke_patient_consent(
    db: Session,
    consent_id: int,
    patient: User,
) -> ConsentRequest | None:
    consent = db.scalar(
        select(ConsentRequest)
        .where(ConsentRequest.id == consent_id)
        .where(ConsentRequest.patient_id == patient.id)
    )
    if consent is None:
        return None
    if consent.status == "Active" and not is_consent_active(consent):
        expire_consent_if_needed(db, consent)
        return None
    if consent.status != "Active":
        return None

    consent.status = "Revoked"
    consent.revoked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(consent)
    create_audit_log(
        db=db,
        actor_user_id=patient.id,
        actor_role=patient.role,
        action="CONSENT_REVOKED",
        target_type="ConsentRequest",
        target_id=consent.id,
        description=f"Patient revoked access for doctor {consent.doctor_id}.",
    )
    return consent


def is_consent_active(consent: ConsentRequest) -> bool:
    if consent.status != "Active":
        return False

    if consent.expires_at is None:
        return False

    now = datetime.now(timezone.utc)

    return _as_utc(consent.expires_at) > now


def expire_consent_if_needed(
    db: Session,
    consent: ConsentRequest,
) -> ConsentRequest:
    if (
        consent.status == "Active"
        and consent.expires_at is not None
        and _as_utc(consent.expires_at) <= datetime.now(timezone.utc)
    ):
        consent.status = "Expired"

        db.commit()
        db.refresh(consent)

        create_audit_log(
            db=db,
            actor_user_id=consent.doctor_id,
            actor_role="Doctor",
            action="CONSENT_EXPIRED",
            target_type="ConsentRequest",
            target_id=consent.id,
            description=(
                f"Consent request {consent.id} expired for "
                f"patient {consent.patient_id}."
            ),
        )

    return consent


def check_active_consent(
    db: Session,
    doctor_id: int,
    patient_id: int,
) -> bool:
    consent = db.scalar(
        select(ConsentRequest)
        .where(
            ConsentRequest.doctor_id == doctor_id
        )
        .where(
            ConsentRequest.patient_id == patient_id
        )
        .where(
            ConsentRequest.status == "Active"
        )
    )

    if consent is None:
        return False

    if consent.expires_at is None:
        return False

    if _as_utc(consent.expires_at) <= datetime.now(timezone.utc):
        expire_consent_if_needed(db, consent)
        return False

    return True
