from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health import (
    Allergy,
    MedicalCondition,
    PatientMedication,
)


def create_allergy(
    db: Session,
    patient_id: int,
    allergen: str,
    reaction: str | None = None,
    severity: str | None = None,
):
    allergy = Allergy(
        patient_id=patient_id,
        allergen=allergen,
        reaction=reaction,
        severity=severity,
    )

    db.add(allergy)
    db.commit()
    db.refresh(allergy)

    return allergy


def get_patient_allergies(
    db: Session,
    patient_id: int,
):
    return db.scalars(
        select(Allergy)
        .where(Allergy.patient_id == patient_id)
        .order_by(Allergy.recorded_at.desc())
    ).all()


def create_condition(
    db: Session,
    patient_id: int,
    condition_name: str,
    notes: str | None = None,
):
    condition = MedicalCondition(
        patient_id=patient_id,
        condition_name=condition_name,
        notes=notes,
    )

    db.add(condition)
    db.commit()
    db.refresh(condition)

    return condition


def get_patient_conditions(
    db: Session,
    patient_id: int,
):
    return db.scalars(
        select(MedicalCondition)
        .where(MedicalCondition.patient_id == patient_id)
        .order_by(MedicalCondition.recorded_at.desc())
    ).all()


def create_patient_medication(
    db: Session,
    patient_id: int,
    medication_name: str,
    rxnorm_code: str | None = None,
    dose: str | None = None,
    frequency: str | None = None,
    started_at: datetime | None = None,
    notes: str | None = None,
):
    medication = PatientMedication(
        patient_id=patient_id,
        medication_name=medication_name,
        rxnorm_code=rxnorm_code,
        dose=dose,
        frequency=frequency,
        started_at=started_at,
        status="Active",
        notes=notes,
    )

    db.add(medication)
    db.commit()
    db.refresh(medication)

    return medication


def get_patient_medications(
    db: Session,
    patient_id: int,
):
    return db.scalars(
        select(PatientMedication)
        .where(PatientMedication.patient_id == patient_id)
        .order_by(PatientMedication.recorded_at.desc())
    ).all()