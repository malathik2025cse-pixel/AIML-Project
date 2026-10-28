from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.prescription import Prescription, PrescriptionItem
from app.models.medication import MedicationReference


def create_prescription(
    db,
    consultation_id,
    doctor_id,
    patient_id,
    doctor_notes,
    items,
    status="Proposed",
):
    prescription = Prescription(
        consultation_id=consultation_id,
        doctor_id=doctor_id,
        patient_id=patient_id,
        doctor_notes=doctor_notes,
        status=status,
    )

    db.add(prescription)
    db.flush()

    for item in items:
        rxnorm_code = item.get("rxnorm_code")

        if rxnorm_code:
            medication = db.scalar(
                select(MedicationReference).where(
                    MedicationReference.rxcui == rxnorm_code
                )
            )

            if medication is None:
                raise ValueError(
                    f"Unknown RxNorm code: {rxnorm_code}"
                )

        prescription_item = PrescriptionItem(
            prescription_id=prescription.id,
            medication_name=item["medication_name"],
            rxnorm_code=rxnorm_code,
            dose=item["dose"],
            frequency=item["frequency"],
            duration=item["duration"],
            instructions=item.get("instructions"),
        )

        db.add(prescription_item)

    db.commit()
    db.refresh(prescription)

    return prescription


def finalize_prescription(
    db: Session,
    prescription_id: int,
):
    prescription = db.scalar(
        select(Prescription).where(
            Prescription.id == prescription_id
        )
    )

    if prescription is None:
        return None

    if prescription.status != "Proposed":
        return None

    prescription.status = "Finalized"

    db.commit()
    db.refresh(prescription)

    return prescription


def get_prescription(db: Session, prescription_id: int):
    return db.scalar(
        select(Prescription).where(
            Prescription.id == prescription_id
        )
    )


def get_prescription_items(db: Session, prescription_id: int):
    return db.scalars(
        select(PrescriptionItem)
        .where(PrescriptionItem.prescription_id == prescription_id)
        .order_by(PrescriptionItem.id)
    ).all()


def get_patient_prescriptions(db: Session, patient_id: int):
    return db.scalars(
        select(Prescription)
        .where(Prescription.patient_id == patient_id)
        .order_by(Prescription.prescribed_at.desc())
    ).all()


def get_doctor_prescriptions(db: Session, doctor_id: int):
    return db.scalars(
        select(Prescription)
        .where(Prescription.doctor_id == doctor_id)
        .order_by(Prescription.prescribed_at.desc())
    ).all()
