from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.consultation import Consultation


def create_consultation(
    db: Session,
    doctor_id: int,
    patient_id: int,
    reason_for_visit: str,
    clinical_notes: str | None = None,
    assessment: str | None = None,
):
    consultation = Consultation(
        doctor_id=doctor_id,
        patient_id=patient_id,
        reason_for_visit=reason_for_visit,
        clinical_notes=clinical_notes,
        assessment=assessment,
        status="Completed",
    )

    db.add(consultation)
    db.commit()
    db.refresh(consultation)

    return consultation


def get_consultation(
    db: Session,
    consultation_id: int,
):
    return db.scalar(
        select(Consultation).where(
            Consultation.id == consultation_id
        )
    )


def get_patient_consultations(
    db: Session,
    patient_id: int,
):
    return db.scalars(
        select(Consultation)
        .where(Consultation.patient_id == patient_id)
        .order_by(Consultation.started_at.desc())
    ).all()


def get_doctor_consultations(
    db: Session,
    doctor_id: int,
):
    return db.scalars(
        select(Consultation)
        .where(Consultation.doctor_id == doctor_id)
        .order_by(Consultation.started_at.desc())
    ).all()