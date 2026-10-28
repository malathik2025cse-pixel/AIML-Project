"""Idempotently seed the explicitly synthetic MedShield application demo."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.models import User
from app.models.health import Allergy, MedicalCondition, PatientMedication
from app.services.admin_service import generate_unique_user_id
from app.models.consent import ConsentRequest
from app.models.medical_record import MedicalRecord

PASSWORD = "DemoPass!2026"


def main() -> None:
    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.role == "Admin"))
        if admin is None:
            admin = User(email="admin@medshield.test", password_hash=hash_password(PASSWORD),
                         role="Admin", status="Active", is_active=True)
            db.add(admin)
            db.commit()
        for role, prefix in (("Patient", "patient"), ("Doctor", "doctor")):
            for number in range(1, 11):
                email = f"{prefix}{number:02d}@medshield.test"
                user = db.scalar(select(User).where(User.email == email))
                if user is None:
                    user = User(email=email, password_hash=hash_password(PASSWORD), role=role,
                                status="Active", is_active=True,
                                medical_registration_number=f"DEMO-{number:04d}" if role == "Doctor" else None,
                                registration_authority="Synthetic Demonstration" if role == "Doctor" else None,
                                qualification="MD" if role == "Doctor" else None,
                                specialization="General Medicine" if role == "Doctor" else None,
                                years_of_practice=5 if role == "Doctor" else None,
                                hospital_clinic="MedShield Demonstration Clinic" if role == "Doctor" else None)
                    db.add(user)
                    db.flush()
                if user.unique_user_id is None:
                    user.unique_user_id = generate_unique_user_id(db, role)
                    db.commit()
                if role == "Patient":
                    if db.scalar(select(MedicalRecord).where(MedicalRecord.patient_id == user.id)) is None:
                        db.add(MedicalRecord(patient_id=user.id, blood_group=("O+" if number == 1 else None)))
                    if number == 1 and db.scalar(select(PatientMedication).where(PatientMedication.patient_id == user.id)) is None:
                        db.add(PatientMedication(patient_id=user.id, medication_name="Amlodipine", dose="5 mg", frequency="Once daily", status="Active"))
                    if number == 2 and db.scalar(select(Allergy).where(Allergy.patient_id == user.id)) is None:
                        db.add(Allergy(patient_id=user.id, allergen="Penicillin", reaction="Rash", severity="Moderate"))
                    if number == 3 and db.scalar(select(MedicalCondition).where(MedicalCondition.patient_id == user.id)) is None:
                        db.add(MedicalCondition(patient_id=user.id, condition_name="Hypertension"))
                    if number == 4 and db.scalar(select(PatientMedication).where(PatientMedication.patient_id == user.id)) is None:
                        now = datetime.now(timezone.utc)
                        db.add_all([
                            PatientMedication(patient_id=user.id, medication_name="Metformin", dose="500 mg", frequency="Twice daily", status="Active", started_at=now - timedelta(days=180)),
                            PatientMedication(patient_id=user.id, medication_name="Aspirin", dose="81 mg", frequency="Once daily", status="Stopped", started_at=now - timedelta(days=365), stopped_at=now - timedelta(days=90)),
                        ])
                    db.commit()
        demo_doctor = db.scalar(select(User).where(User.email == "doctor01@medshield.test"))
        demo_patient = db.scalar(select(User).where(User.email == "patient01@medshield.test"))
        consent = db.scalar(select(ConsentRequest).where(ConsentRequest.doctor_id == demo_doctor.id, ConsentRequest.patient_id == demo_patient.id))
        if consent is None:
            now = datetime.now(timezone.utc)
            db.add(ConsentRequest(doctor_id=demo_doctor.id, patient_id=demo_patient.id,
                                  status="Active", requested_at=now, responded_at=now,
                                  expires_at=now + timedelta(hours=1)))
            db.commit()
        doctor_two = db.scalar(select(User).where(User.email == "doctor02@medshield.test"))
        patient_two = db.scalar(select(User).where(User.email == "patient02@medshield.test"))
        pending = db.scalar(select(ConsentRequest).where(ConsentRequest.doctor_id == doctor_two.id, ConsentRequest.patient_id == patient_two.id))
        if pending is None:
            db.add(ConsentRequest(doctor_id=doctor_two.id, patient_id=patient_two.id,
                                  status="Pending", requested_at=datetime.now(timezone.utc)))
            db.commit()
        print("Synthetic demo seed complete (10 patients, 10 doctors, 1 admin).")
        print("Demo-only password for seeded patient/doctor accounts and any newly created demo admin: DemoPass!2026")
    finally:
        db.close()


if __name__ == "__main__":
    main()
