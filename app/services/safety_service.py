from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.safety import SafetyCheck, SafetyFinding


def create_safety_check(
    db: Session,
    consultation_id: int,
    prescription_id: int | None,
    doctor_id: int,
    patient_id: int,
    findings: list,
):
    safety_check = SafetyCheck(
        consultation_id=consultation_id,
        prescription_id=prescription_id,
        doctor_id=doctor_id,
        patient_id=patient_id,
        status="Pending Review",
    )

    db.add(safety_check)
    db.flush()

    for finding in findings:
        safety_finding = SafetyFinding(
            safety_check_id=safety_check.id,
            category=finding.category,
            severity=finding.severity,
            title=finding.title,
            explanation=finding.explanation,
            source=finding.source,
        )

        db.add(safety_finding)

    db.commit()
    db.refresh(safety_check)

    return safety_check


def get_safety_check(
    db: Session,
    safety_check_id: int,
):
    return db.scalar(
        select(SafetyCheck).where(
            SafetyCheck.id == safety_check_id
        )
    )


def get_safety_findings(
    db: Session,
    safety_check_id: int,
):
    return db.scalars(
        select(SafetyFinding)
        .where(
            SafetyFinding.safety_check_id
            == safety_check_id
        )
        .order_by(SafetyFinding.id)
    ).all()