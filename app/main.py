from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.auth import (
    create_access_token,
    hash_password,
    verify_password,
)

from app.database import get_db, settings
from app.dependencies import get_current_user, require_admin
from app.models import User, Allergy, MedicalCondition, PatientMedication
from app.models.medication import MedicationReference

from app.schemas import (
    AdminLoginRequest,
    ConsentRequestCreate,
    ConsentRequestResponse,
    LoginRequest,
    RegistrationRequest,
    MedicalRecordCreate,
    MedicalRecordResponse,
    ConsultationCreate,
    ConsultationResponse,
    PrescriptionCreate,
    SafetyCheckCreate,
    PrescriptionResponse,
    PrescriptionItemResponse,
    MedicationSearchResponse,
    AllergyCreate,
    AllergyResponse,
    MedicalConditionCreate,
    MedicalConditionResponse,
    PatientMedicationCreate,
    PatientMedicationResponse,
)

from app.services.admin import get_all_users

from app.services.admin_service import (
    approve_user,
    reject_user,
)

from app.services.auth_service import authenticate_user

from app.services.consent_service import (
    create_consent_request,
    get_doctor_consent_requests,
    get_patient_consent_requests,
    approve_consent_request,
    reject_consent_request,
    check_active_consent,
    revoke_patient_consent,
)

from app.services.medical_record_service import (
    create_or_update_record,
    get_patient_record,
)

from app.services.consultation_service import (
    create_consultation,
    get_consultation,
    get_patient_consultations,
)

from app.services.prescription_service import (
    create_prescription,
    finalize_prescription,
    get_prescription,
    get_prescription_items,
    get_patient_prescriptions,
)

from app.services.medication_service import (
    search_and_store_medications,
)

from app.services.health_service import (
    create_allergy,
    get_patient_allergies,
    create_condition,
    get_patient_conditions,
    create_patient_medication,
    get_patient_medications,
)

from app.services.safety_engine import run_safety_engine
from app.services.ml_service import build_features, predict_review_signal

from app.services.safety_service import (
    create_safety_check,
    get_safety_check,
    get_safety_findings,
)

from app.models.safety import SafetyCheck
from app.models.audit import AuditLog
from app.services.audit_service import create_audit_log


app = FastAPI(
    title="MedShield API",
    description="Consent-First, Explainable Medication Safety Platform",
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()] if settings.cors_origins else [
        "http://localhost:5174",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ADMIN AUDIT LOGS
# ============================================================


@app.get("/admin/audit-logs")
def get_admin_audit_logs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(current_user)

    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .all()
    )

    return [
        {
            "id": log.id,
            "actor_user_id": log.actor_user_id,
            "actor_role": log.actor_role,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "description": log.description,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


# ============================================================
# BASIC
# ============================================================


@app.get("/")
def root():
    return {
        "message": "MedShield API is running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


# ============================================================
# AUTHENTICATION
# ============================================================


@app.post("/auth/register")
def register(
    data: RegistrationRequest,
    db: Session = Depends(get_db),
):
    if data.role not in {"Patient", "Doctor"}:
        raise HTTPException(
            status_code=400,
            detail="Only Patient and Doctor registration is allowed",
        )

    existing_user = db.scalar(
        select(User).where(User.email == data.email)
    )

    if existing_user is not None:
        raise HTTPException(
            status_code=400,
            detail="Email is already registered",
        )

    # --------------------------------------------------------
    # Doctor professional verification fields
    # --------------------------------------------------------

    if data.role == "Doctor":

        required_doctor_fields = {
            "medical_registration_number": data.medical_registration_number,
            "registration_authority": data.registration_authority,
            "qualification": data.qualification,
            "specialization": data.specialization,
            "years_of_practice": data.years_of_practice,
            "hospital_clinic": data.hospital_clinic,
        }

        missing_fields = [
            field
            for field, value in required_doctor_fields.items()
            if value is None or value == ""
        ]

        if missing_fields:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "All doctor verification fields are required",
                    "missing_fields": missing_fields,
                },
            )

        if data.years_of_practice < 0:
            raise HTTPException(
                status_code=400,
                detail="Years of practice cannot be negative",
            )

    # --------------------------------------------------------
    # Create pending account
    # --------------------------------------------------------

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
        status="Pending Approval",
        is_active=False,
        medical_registration_number=data.medical_registration_number,
        registration_authority=data.registration_authority,
        qualification=data.qualification,
        specialization=data.specialization,
        years_of_practice=data.years_of_practice,
        hospital_clinic=data.hospital_clinic,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    create_audit_log(
        db=db,
        actor_user_id=user.id,
        actor_role=user.role,
        action="REGISTRATION_SUBMITTED",
        target_type="User",
        target_id=user.id,
        description=(
            f"{user.role} registration submitted for admin approval."
        ),
    )

    return {
        "message": "Registration submitted for admin approval",
        "status": user.status,
        "role": user.role,
        "unique_user_id": user.unique_user_id,
    }


@app.post("/auth/login")
def login(
    data: LoginRequest,
    db: Session = Depends(get_db),
):
    user = authenticate_user(
        db=db,
        email=data.email,
        password=data.password,
    )

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password, or account is not active",
        )

    access_token = create_access_token(
        user_id=user.id,
        role=user.role,
    )

    return {
        "message": "Login successful",
        "role": user.role,
        "status": user.status,
        "unique_user_id": user.unique_user_id,
        "access_token": access_token,
        "token_type": "bearer",
    }


# ============================================================
# AUTH TEST
# ============================================================


@app.post("/auth/test")
def auth_test(
    data: LoginRequest,
    db: Session = Depends(get_db),
):
    user = authenticate_user(
        db=db,
        email=data.email,
        password=data.password,
    )

    return {
        "authenticated": user is not None
    }


# ============================================================
# ADMIN AUTHENTICATION
# ============================================================


@app.post("/admin/login")
def admin_login(
    data: AdminLoginRequest,
    db: Session = Depends(get_db),
):
    user = db.scalar(
        select(User).where(
            User.email == data.email,
            User.role == "Admin",
        )
    )

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid Admin email or password",
        )

    if not verify_password(
        data.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid Admin email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Admin account is not active",
        )

    access_token = create_access_token(
        user_id=user.id,
        role=user.role,
    )

    return {
        "message": "Admin login successful",
        "role": "Admin",
        "status": user.status,
        "unique_user_id": user.unique_user_id,
        "access_token": access_token,
        "token_type": "bearer",
    }


# ============================================================
# ACCOUNT STATUS
# ============================================================


@app.get("/auth/account-status")
def account_status(
    email: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    user = db.scalar(
        select(User).where(User.email == email)
    )

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Account not found",
        )

    return {
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "is_active": user.is_active,
        "unique_user_id": user.unique_user_id,
    }


# ============================================================
# ADMIN USER MANAGEMENT
# ============================================================


@app.get("/admin/users")
def get_admin_users(
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    users = get_all_users(db)

    return [
        {
            "id": user.id,
            "unique_user_id": user.unique_user_id,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "is_active": user.is_active,
            "medical_registration_number": user.medical_registration_number,
            "registration_authority": user.registration_authority,
            "qualification": user.qualification,
            "specialization": user.specialization,
            "years_of_practice": user.years_of_practice,
            "hospital_clinic": user.hospital_clinic,
        }
        for user in users
    ]


@app.post("/admin/users/{user_id}/approve")
def approve_user_account(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    user = approve_user(
        db=db,
        user_id=user_id,
    )

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found or cannot be approved",
        )

    create_audit_log(
        db=db,
        actor_user_id=admin_user.id,
        actor_role=admin_user.role,
        action="REGISTRATION_APPROVED",
        target_type="User",
        target_id=user.id,
        description=(
            f"Admin approved {user.role} registration for user "
            f"{user.id} and activated the account."
        ),
    )

    return {
        "message": "User approved successfully",
        "user_id": user.id,
        "role": user.role,
        "status": user.status,
        "is_active": user.is_active,
        "unique_user_id": user.unique_user_id,
    }


@app.post("/admin/users/{user_id}/reject")
def reject_user_account(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    user = reject_user(
        db=db,
        user_id=user_id,
    )

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found or cannot be rejected",
        )

    create_audit_log(
        db=db,
        actor_user_id=admin_user.id,
        actor_role=admin_user.role,
        action="REGISTRATION_REJECTED",
        target_type="User",
        target_id=user.id,
        description=(
            f"Admin rejected {user.role} registration for user "
            f"{user.id}."
        ),
    )

    return {
        "message": "User rejected successfully",
        "user_id": user.id,
        "role": user.role,
        "status": user.status,
        "is_active": user.is_active,
        "unique_user_id": user.unique_user_id,
    }


# ============================================================
# CONSENT — DOCTOR REQUESTS PATIENT ACCESS
# ============================================================


@app.post(
    "/doctor/consent-requests",
    response_model=ConsentRequestResponse,
)
def request_patient_consent(
    data: ConsentRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    patient = db.scalar(
        select(User).where(
            User.unique_user_id == data.patient_unique_id,
            User.role == "Patient",
        )
    )

    if patient is None:
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    if not patient.is_active:
        raise HTTPException(
            status_code=403,
            detail="Patient account is not active",
        )

    consent = create_consent_request(
        db=db,
        doctor=current_user,
        patient=patient,
    )

    create_audit_log(
        db=db,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="CONSENT_REQUESTED",
        target_type="ConsentRequest",
        target_id=consent.id,
        description=(
            f"Doctor requested access to patient {patient.id}."
        ),
    )

    return ConsentRequestResponse(
        id=consent.id,
        doctor_id=consent.doctor_id,
        patient_id=consent.patient_id,
        status=consent.status,
        requested_at=consent.requested_at.isoformat(),
        responded_at=(
            consent.responded_at.isoformat()
            if consent.responded_at
            else None
        ),
        expires_at=(
            consent.expires_at.isoformat()
            if consent.expires_at
            else None
        ),
        revoked_at=(
            consent.revoked_at.isoformat()
            if consent.revoked_at
            else None
        ),
    )


# ============================================================
# CONSENT — DOCTOR VIEW REQUESTS
# ============================================================


@app.get(
    "/doctor/consent-requests",
    response_model=list[ConsentRequestResponse],
)
def doctor_consent_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    requests = get_doctor_consent_requests(
        db=db,
        doctor=current_user,
    )

    return [
        ConsentRequestResponse(
            id=request.id,
            doctor_id=request.doctor_id,
            patient_id=request.patient_id,
            status=request.status,
            requested_at=request.requested_at.isoformat(),
            responded_at=(
                request.responded_at.isoformat()
                if request.responded_at
                else None
            ),
            expires_at=(
                request.expires_at.isoformat()
                if request.expires_at
                else None
            ),
            revoked_at=(
                request.revoked_at.isoformat()
                if request.revoked_at
                else None
            ),
            patient_unique_id=db.get(User, request.patient_id).unique_user_id,
        )
        for request in requests
    ]


# ============================================================
# CONSENT — PATIENT VIEW REQUESTS
# ============================================================


@app.get(
    "/patient/consent-requests",
    response_model=list[ConsentRequestResponse],
)
def patient_consent_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    requests = get_patient_consent_requests(
        db=db,
        patient=current_user,
    )

    return [
        ConsentRequestResponse(
            id=request.id,
            doctor_id=request.doctor_id,
            patient_id=request.patient_id,
            status=request.status,
            requested_at=request.requested_at.isoformat(),
            responded_at=(
                request.responded_at.isoformat()
                if request.responded_at
                else None
            ),
            expires_at=(
                request.expires_at.isoformat()
                if request.expires_at
                else None
            ),
            revoked_at=(
                request.revoked_at.isoformat()
                if request.revoked_at
                else None
            ),
            doctor_unique_id=db.get(User, request.doctor_id).unique_user_id,
        )
        for request in requests
    ]


# ============================================================
# CONSENT — PATIENT APPROVE
# ============================================================


@app.post(
    "/patient/consent-requests/{consent_id}/approve",
    response_model=ConsentRequestResponse,
)
def approve_patient_consent(
    consent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    consent = approve_consent_request(
        db=db,
        consent_id=consent_id,
        patient=current_user,
    )

    if consent is None:
        raise HTTPException(
            status_code=404,
            detail="Consent request not found or already processed",
        )

    create_audit_log(
        db=db,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="CONSENT_APPROVED",
        target_type="ConsentRequest",
        target_id=consent.id,
        description=(
            f"Patient approved consent request {consent.id} "
            f"for doctor {consent.doctor_id}."
        ),
    )

    return ConsentRequestResponse(
        id=consent.id,
        doctor_id=consent.doctor_id,
        patient_id=consent.patient_id,
        status=consent.status,
        requested_at=consent.requested_at.isoformat(),
        responded_at=(
            consent.responded_at.isoformat()
            if consent.responded_at
            else None
        ),
        expires_at=(
            consent.expires_at.isoformat()
            if consent.expires_at
            else None
        ),
        revoked_at=(
            consent.revoked_at.isoformat()
            if consent.revoked_at
            else None
        ),
    )


# ============================================================
# CONSENT — PATIENT REJECT
# ============================================================


@app.post(
    "/patient/consent-requests/{consent_id}/reject",
    response_model=ConsentRequestResponse,
)
def reject_patient_consent(
    consent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    consent = reject_consent_request(
        db=db,
        consent_id=consent_id,
        patient=current_user,
    )

    if consent is None:
        raise HTTPException(
            status_code=404,
            detail="Consent request not found or already processed",
        )

    create_audit_log(
        db=db,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="CONSENT_REJECTED",
        target_type="ConsentRequest",
        target_id=consent.id,
        description=(
            f"Patient rejected consent request {consent.id} "
            f"for doctor {consent.doctor_id}."
        ),
    )

    return ConsentRequestResponse(
        id=consent.id,
        doctor_id=consent.doctor_id,
        patient_id=consent.patient_id,
        status=consent.status,
        requested_at=consent.requested_at.isoformat(),
        responded_at=(
            consent.responded_at.isoformat()
            if consent.responded_at
            else None
        ),
        expires_at=(
            consent.expires_at.isoformat()
            if consent.expires_at
            else None
        ),
        revoked_at=(
            consent.revoked_at.isoformat()
            if consent.revoked_at
            else None
        ),
    )


@app.post("/patient/consent-requests/{consent_id}/revoke")
def revoke_patient_access(
    consent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Patient":
        raise HTTPException(status_code=403, detail="Patient access required")
    consent = revoke_patient_consent(db, consent_id, current_user)
    if consent is None:
        raise HTTPException(status_code=404, detail="Active consent not found")
    return {"id": consent.id, "status": consent.status, "revoked_at": consent.revoked_at.isoformat()}


# ============================================================
# MEDICAL RECORD — PATIENT VIEW OWN RECORD
# ============================================================


@app.get(
    "/patient/medical-record",
    response_model=MedicalRecordResponse,
)
def view_patient_medical_record(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    record = get_patient_record(
        db=db,
        patient_id=current_user.id,
    )

    if record is None:
        return MedicalRecordResponse(
            id=0, patient_id=current_user.id, blood_group=None,
            allergies=None, medical_conditions=None, current_medications=None,
        )

    return record


# ============================================================
# MEDICAL RECORD — PATIENT CREATE / UPDATE
# ============================================================


@app.post(
    "/patient/medical-record",
    response_model=MedicalRecordResponse,
)
def save_patient_medical_record(
    data: MedicalRecordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    record = create_or_update_record(
        db=db,
        patient=current_user,
        blood_group=data.blood_group,
        allergies=data.allergies,
        medical_conditions=data.medical_conditions,
        current_medications=data.current_medications,
    )

    return record


# ============================================================
# MEDICAL RECORD — DOCTOR ACCESS WITH CONSENT CHECK
# ============================================================


@app.get(
    "/doctor/patient/{patient_id}/medical-record",
    response_model=MedicalRecordResponse,
)
def doctor_view_patient_record(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    consent_allowed = check_active_consent(
        db=db,
        doctor_id=current_user.id,
        patient_id=patient_id,
    )

    if not consent_allowed:
        raise HTTPException(
            status_code=403,
            detail="Active consent required",
        )

    record = get_patient_record(
        db=db,
        patient_id=patient_id,
    )

    if record is None:
        return MedicalRecordResponse(
            id=0, patient_id=patient_id, blood_group=None,
            allergies=None, medical_conditions=None, current_medications=None,
        )

    return record


# ============================================================
# CONSULTATION — DOCTOR CREATE
# ============================================================


@app.post(
    "/doctor/patient/{patient_id}/consultations",
    response_model=ConsultationResponse,
)
def create_patient_consultation(
    patient_id: int,
    data: ConsultationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    patient = db.get(User, patient_id)

    if patient is None or patient.role != "Patient":
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    if not check_active_consent(
        db,
        doctor_id=current_user.id,
        patient_id=patient_id,
    ):
        raise HTTPException(
            status_code=403,
            detail="Active consent required",
        )

    consultation = create_consultation(
        db=db,
        doctor_id=current_user.id,
        patient_id=patient_id,
        reason_for_visit=data.reason_for_visit,
        clinical_notes=data.clinical_notes,
        assessment=data.assessment,
    )

    create_audit_log(
        db=db,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="CONSULTATION_CREATED",
        target_type="Consultation",
        target_id=consultation.id,
        description=(
            f"Doctor created consultation {consultation.id} "
            f"for patient {patient_id}."
        ),
    )

    return ConsultationResponse(
        id=consultation.id,
        doctor_id=consultation.doctor_id,
        patient_id=consultation.patient_id,
        started_at=consultation.started_at.isoformat(),
        reason_for_visit=consultation.reason_for_visit,
        clinical_notes=consultation.clinical_notes,
        assessment=consultation.assessment,
        status=consultation.status,
    )


# ============================================================
# CONSULTATION — DOCTOR VIEW
# ============================================================


@app.get(
    "/doctor/patient/{patient_id}/consultations",
    response_model=list[ConsultationResponse],
)
def view_patient_consultations(
    patient_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    patient = db.get(User, patient_id)

    if patient is None or patient.role != "Patient":
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    if not check_active_consent(
        db,
        doctor_id=current_user.id,
        patient_id=patient_id,
    ):
        raise HTTPException(
            status_code=403,
            detail="Active consent required",
        )

    consultations = get_patient_consultations(
        db,
        patient_id,
    )

    return [
        ConsultationResponse(
            id=item.id,
            doctor_id=item.doctor_id,
            patient_id=item.patient_id,
            started_at=item.started_at.isoformat(),
            reason_for_visit=item.reason_for_visit,
            clinical_notes=item.clinical_notes,
            assessment=item.assessment,
            status=item.status,
        )
        for item in consultations
        if item.doctor_id == current_user.id
    ]


# ============================================================
# CONSULTATION — PATIENT VIEW
# ============================================================


@app.get(
    "/patient/consultations",
    response_model=list[ConsultationResponse],
)
def view_my_consultations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    consultations = get_patient_consultations(
        db,
        current_user.id,
    )

    return [
        ConsultationResponse(
            id=item.id,
            doctor_id=item.doctor_id,
            patient_id=item.patient_id,
            started_at=item.started_at.isoformat(),
            reason_for_visit=item.reason_for_visit,
            clinical_notes=item.clinical_notes,
            assessment=item.assessment,
            status=item.status,
        )
        for item in consultations
    ]


# ============================================================
# PRESCRIPTION — DOCTOR CREATE
# ============================================================


@app.post(
    "/doctor/patient/{patient_id}/prescriptions",
    response_model=PrescriptionResponse,
)
def create_patient_prescription(
    patient_id: int,
    data: PrescriptionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    patient = db.get(User, patient_id)

    if patient is None or patient.role != "Patient":
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    if not check_active_consent(
        db,
        doctor_id=current_user.id,
        patient_id=patient_id,
    ):
        raise HTTPException(
            status_code=403,
            detail="Active consent required",
        )

    if not data.items:
        raise HTTPException(
            status_code=400,
            detail="At least one medication is required",
        )

    consultation = get_consultation(
        db,
        data.consultation_id,
    )

    if consultation is None:
        raise HTTPException(
            status_code=404,
            detail="Consultation not found",
        )

    if (
        consultation.doctor_id != current_user.id
        or consultation.patient_id != patient_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Consultation does not belong to this doctor and patient",
        )

    try:
        prescription = create_prescription(
            db=db,
            consultation_id=data.consultation_id,
            doctor_id=current_user.id,
            patient_id=patient_id,
            doctor_notes=data.doctor_notes,
            items=[item.model_dump() for item in data.items],
            status="Proposed",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    create_audit_log(
        db=db,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="PRESCRIPTION_PROPOSED",
        target_type="Prescription",
        target_id=prescription.id,
        description=(
            f"Doctor proposed prescription {prescription.id} "
            f"for patient {patient_id}."
        ),
    )

    prescription_items = get_prescription_items(
        db,
        prescription.id,
    )

    return PrescriptionResponse(
        id=prescription.id,
        consultation_id=prescription.consultation_id,
        doctor_id=prescription.doctor_id,
        patient_id=prescription.patient_id,
        prescribed_at=prescription.prescribed_at.isoformat(),
        status=prescription.status,
        doctor_notes=prescription.doctor_notes,
        items=[
            PrescriptionItemResponse(
                id=item.id,
                prescription_id=item.prescription_id,
                medication_name=item.medication_name,
                rxnorm_code=item.rxnorm_code,
                dose=item.dose,
                frequency=item.frequency,
                duration=item.duration,
                instructions=item.instructions,
            )
            for item in prescription_items
        ],
    )


# ============================================================
# PRESCRIPTION — DOCTOR FINALIZE
# ============================================================


@app.post(
    "/doctor/prescriptions/{prescription_id}/finalize",
    response_model=PrescriptionResponse,
)
def finalize_patient_prescription(
    prescription_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    prescription = get_prescription(
        db,
        prescription_id,
    )

    if prescription is None:
        raise HTTPException(
            status_code=404,
            detail="Prescription not found",
        )

    if prescription.doctor_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to finalize this prescription",
        )

    if not check_active_consent(
        db,
        doctor_id=current_user.id,
        patient_id=prescription.patient_id,
    ):
        raise HTTPException(
            status_code=403,
            detail="Active consent required",
        )

    if prescription.status != "Proposed":
        raise HTTPException(
            status_code=400,
            detail="Only Proposed prescriptions can be finalized",
        )

    latest_safety_check = db.scalar(
        select(SafetyCheck)
        .where(
            SafetyCheck.prescription_id == prescription.id,
            SafetyCheck.doctor_id == current_user.id,
            SafetyCheck.patient_id == prescription.patient_id,
        )
        .order_by(SafetyCheck.id.desc())
        .limit(1)
    )

    if latest_safety_check is None:
        raise HTTPException(
            status_code=400,
            detail="Safety check is required before finalizing the prescription",
        )

    if latest_safety_check.status != "Reviewed":
        raise HTTPException(
            status_code=400,
            detail="Safety check must be reviewed before finalizing the prescription",
        )

    if latest_safety_check.doctor_decision != "Approved":
        raise HTTPException(
            status_code=400,
            detail=(
                "Prescription cannot be finalized because the safety decision "
                "is not Approved"
            ),
        )

    prescription = finalize_prescription(
        db,
        prescription.id,
    )

    if prescription is None:
        raise HTTPException(
            status_code=404,
            detail="Prescription not found",
        )

    create_audit_log(
        db=db,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="PRESCRIPTION_FINALIZED",
        target_type="Prescription",
        target_id=prescription.id,
        description=(
            f"Doctor finalized prescription {prescription.id} "
            f"for patient {prescription.patient_id}."
        ),
    )

    prescription_items = get_prescription_items(
        db,
        prescription.id,
    )

    return PrescriptionResponse(
        id=prescription.id,
        consultation_id=prescription.consultation_id,
        doctor_id=prescription.doctor_id,
        patient_id=prescription.patient_id,
        prescribed_at=prescription.prescribed_at.isoformat(),
        status=prescription.status,
        doctor_notes=prescription.doctor_notes,
        items=[
            PrescriptionItemResponse(
                id=item.id,
                prescription_id=item.prescription_id,
                medication_name=item.medication_name,
                rxnorm_code=item.rxnorm_code,
                dose=item.dose,
                frequency=item.frequency,
                duration=item.duration,
                instructions=item.instructions,
            )
            for item in prescription_items
        ],
    )


# ============================================================
# PRESCRIPTION — PATIENT VIEW
# ============================================================


@app.get(
    "/patient/prescriptions",
    response_model=list[PrescriptionResponse],
)
def view_my_prescriptions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    prescriptions = get_patient_prescriptions(
        db,
        current_user.id,
    )

    results = []

    for prescription in prescriptions:
        items = get_prescription_items(
            db,
            prescription.id,
        )

        results.append(
            PrescriptionResponse(
                id=prescription.id,
                consultation_id=prescription.consultation_id,
                doctor_id=prescription.doctor_id,
                patient_id=prescription.patient_id,
                prescribed_at=prescription.prescribed_at.isoformat(),
                status=prescription.status,
                doctor_notes=prescription.doctor_notes,
                items=[
                    PrescriptionItemResponse(
                        id=item.id,
                        prescription_id=item.prescription_id,
                        medication_name=item.medication_name,
                        rxnorm_code=item.rxnorm_code,
                        dose=item.dose,
                        frequency=item.frequency,
                        duration=item.duration,
                        instructions=item.instructions,
                    )
                    for item in items
                ],
            )
        )

    return results


# ============================================================
# PRESCRIPTION — DOCTOR VIEW PATIENT PRESCRIPTIONS
# ============================================================


@app.get(
    "/doctor/patient/{patient_id}/prescriptions",
    response_model=list[PrescriptionResponse],
)
def doctor_view_patient_prescriptions(
    patient_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    patient = db.get(User, patient_id)
    if patient is None or patient.role != "Patient":
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    if not check_active_consent(
        db,
        doctor_id=current_user.id,
        patient_id=patient_id,
    ):
        raise HTTPException(
            status_code=403,
            detail="Active consent required",
        )

    prescriptions = get_patient_prescriptions(
        db,
        patient_id,
    )

    results = []
    for prescription in prescriptions:
        items = get_prescription_items(
            db,
            prescription.id,
        )
        results.append(
            PrescriptionResponse(
                id=prescription.id,
                consultation_id=prescription.consultation_id,
                doctor_id=prescription.doctor_id,
                patient_id=prescription.patient_id,
                prescribed_at=prescription.prescribed_at.isoformat(),
                status=prescription.status,
                doctor_notes=prescription.doctor_notes,
                items=[
                    PrescriptionItemResponse(
                        id=item.id,
                        prescription_id=item.prescription_id,
                        medication_name=item.medication_name,
                        rxnorm_code=item.rxnorm_code,
                        dose=item.dose,
                        frequency=item.frequency,
                        duration=item.duration,
                        instructions=item.instructions,
                    )
                    for item in items
                ],
            )
        )

    return results


# ============================================================
# MEDICATION SEARCH
# ============================================================


@app.get(
    "/doctor/medications/search",
    response_model=list[MedicationSearchResponse],
)
def search_medications(
    term: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    term = term.strip()

    if not term:
        raise HTTPException(
            status_code=400,
            detail="Medication search term is required",
        )

    if len(term) < 2:
        raise HTTPException(
            status_code=400,
            detail="Medication search term must contain at least 2 characters",
        )

    try:
        results = search_and_store_medications(
            db=db,
            term=term,
        )
    except Exception:
        local_refs = db.scalars(
            select(MedicationReference).where(
                MedicationReference.name.ilike(f"%{term}%")
            ).limit(10)
        ).all()
        results = [
            {
                "id": m.id,
                "rxcui": m.rxcui,
                "name": m.name,
                "synonym": m.synonym,
                "term_type": m.term_type,
                "source": m.source or "LOCAL",
                "match_score": 100,
                "match_rank": 1,
            }
            for m in local_refs
        ]

    return [
        MedicationSearchResponse(**item)
        for item in results
    ]


# ============================================================
# PATIENT ALLERGIES
# ============================================================


@app.get(
    "/patient/health/allergies",
    response_model=list[AllergyResponse],
)
def view_my_allergies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    allergies = get_patient_allergies(
        db,
        current_user.id,
    )

    return [
        AllergyResponse(
            id=item.id,
            patient_id=item.patient_id,
            allergen=item.allergen,
            reaction=item.reaction,
            severity=item.severity,
            recorded_at=item.recorded_at.isoformat(),
        )
        for item in allergies
    ]


@app.post(
    "/patient/health/allergies",
    response_model=AllergyResponse,
)
def add_my_allergy(
    data: AllergyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    if not data.allergen.strip():
        raise HTTPException(
            status_code=400,
            detail="Allergen is required",
        )

    allergy = create_allergy(
        db=db,
        patient_id=current_user.id,
        allergen=data.allergen.strip(),
        reaction=data.reaction,
        severity=data.severity,
    )

    return AllergyResponse(
        id=allergy.id,
        patient_id=allergy.patient_id,
        allergen=allergy.allergen,
        reaction=allergy.reaction,
        severity=allergy.severity,
        recorded_at=allergy.recorded_at.isoformat(),
    )


@app.delete("/patient/health/allergies/{allergy_id}")
def delete_my_allergy(
    allergy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(status_code=403, detail="Patient access required")
    allergy = db.get(Allergy, allergy_id)
    if allergy is None or allergy.patient_id != current_user.id:
        raise HTTPException(status_code=404, detail="Allergy not found")
    db.delete(allergy)
    db.commit()
    return {"message": "Allergy deleted", "id": allergy_id}


# ============================================================
# PATIENT CONDITIONS
# ============================================================


@app.get(
    "/patient/health/conditions",
    response_model=list[MedicalConditionResponse],
)
def view_my_conditions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    conditions = get_patient_conditions(
        db,
        current_user.id,
    )

    return [
        MedicalConditionResponse(
            id=item.id,
            patient_id=item.patient_id,
            condition_name=item.condition_name,
            notes=item.notes,
            recorded_at=item.recorded_at.isoformat(),
        )
        for item in conditions
    ]


@app.post(
    "/patient/health/conditions",
    response_model=MedicalConditionResponse,
)
def add_my_condition(
    data: MedicalConditionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    if not data.condition_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Condition name is required",
        )

    condition = create_condition(
        db=db,
        patient_id=current_user.id,
        condition_name=data.condition_name.strip(),
        notes=data.notes,
    )

    return MedicalConditionResponse(
        id=condition.id,
        patient_id=condition.patient_id,
        condition_name=condition.condition_name,
        notes=condition.notes,
        recorded_at=condition.recorded_at.isoformat(),
    )


@app.delete("/patient/health/conditions/{condition_id}")
def delete_my_condition(
    condition_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(status_code=403, detail="Patient access required")
    condition = db.get(MedicalCondition, condition_id)
    if condition is None or condition.patient_id != current_user.id:
        raise HTTPException(status_code=404, detail="Condition not found")
    db.delete(condition)
    db.commit()
    return {"message": "Condition deleted", "id": condition_id}


# ============================================================
# PATIENT MEDICATIONS
# ============================================================


@app.get(
    "/patient/health/medications",
    response_model=list[PatientMedicationResponse],
)
def view_my_medications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    medications = get_patient_medications(
        db,
        current_user.id,
    )

    return [
        PatientMedicationResponse(
            id=item.id,
            patient_id=item.patient_id,
            medication_name=item.medication_name,
            rxnorm_code=item.rxnorm_code,
            dose=item.dose,
            frequency=item.frequency,
            started_at=(
                item.started_at.isoformat()
                if item.started_at
                else None
            ),
            stopped_at=(
                item.stopped_at.isoformat()
                if item.stopped_at
                else None
            ),
            status=item.status,
            notes=item.notes,
            recorded_at=item.recorded_at.isoformat(),
        )
        for item in medications
    ]


@app.post(
    "/patient/health/medications",
    response_model=PatientMedicationResponse,
)
def add_my_medication(
    data: PatientMedicationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    if not data.medication_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Medication name is required",
        )

    started_at = None

    if data.started_at:
        try:
            started_at = datetime.fromisoformat(
                data.started_at
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid started_at datetime",
            )

    medication = create_patient_medication(
        db=db,
        patient_id=current_user.id,
        medication_name=data.medication_name.strip(),
        rxnorm_code=data.rxnorm_code,
        dose=data.dose,
        frequency=data.frequency,
        started_at=started_at,
        notes=data.notes,
    )

    return PatientMedicationResponse(
        id=medication.id,
        patient_id=medication.patient_id,
        medication_name=medication.medication_name,
        rxnorm_code=medication.rxnorm_code,
        dose=medication.dose,
        frequency=medication.frequency,
        started_at=(
            medication.started_at.isoformat()
            if medication.started_at
            else None
        ),
        stopped_at=None,
        status=medication.status,
        notes=medication.notes,
        recorded_at=medication.recorded_at.isoformat(),
    )


@app.delete("/patient/health/medications/{medication_id}")
def delete_my_medication(
    medication_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(status_code=403, detail="Patient access required")
    medication = db.get(PatientMedication, medication_id)
    if medication is None or medication.patient_id != current_user.id:
        raise HTTPException(status_code=404, detail="Medication not found")
    db.delete(medication)
    db.commit()
    return {"message": "Medication removed", "id": medication_id}


@app.patch("/patient/health/medications/{medication_id}/status")
def update_my_medication_status(
    medication_id: int,
    status: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Patient":
        raise HTTPException(status_code=403, detail="Patient access required")
    medication = db.get(PatientMedication, medication_id)
    if medication is None or medication.patient_id != current_user.id:
        raise HTTPException(status_code=404, detail="Medication not found")
    medication.status = status
    if status.lower() == "stopped":
        medication.stopped_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(medication)
    return {"message": "Medication status updated", "id": medication_id, "status": medication.status}


# ============================================================
# DOCTOR — PATIENT SAFETY PROFILE
# ============================================================


@app.get(
    "/doctor/patient/{patient_id}/safety-profile",
)
def get_patient_safety_profile(
    patient_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    patient = db.get(User, patient_id)

    if patient is None or patient.role != "Patient":
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    if not check_active_consent(
        db,
        doctor_id=current_user.id,
        patient_id=patient_id,
    ):
        raise HTTPException(
            status_code=403,
            detail="Active consent required",
        )

    allergies = get_patient_allergies(
        db,
        patient_id,
    )

    conditions = get_patient_conditions(
        db,
        patient_id,
    )

    medications = get_patient_medications(
        db,
        patient_id,
    )
    medical_record = get_patient_record(db=db, patient_id=patient_id)

    return {
        "patient": {
            "id": patient.id,
            "unique_user_id": patient.unique_user_id,
        },
        "blood_group": medical_record.blood_group if medical_record else None,
        "allergies": [
            {
                "id": item.id,
                "allergen": item.allergen,
                "reaction": item.reaction,
                "severity": item.severity,
                "recorded_at": item.recorded_at.isoformat(),
            }
            for item in allergies
        ],
        "conditions": [
            {
                "id": item.id,
                "condition_name": item.condition_name,
                "notes": item.notes,
                "recorded_at": item.recorded_at.isoformat(),
            }
            for item in conditions
        ],
        "medications": [
            {
                "id": item.id,
                "medication_name": item.medication_name,
                "rxnorm_code": item.rxnorm_code,
                "dose": item.dose,
                "frequency": item.frequency,
                "started_at": (
                    item.started_at.isoformat()
                    if item.started_at
                    else None
                ),
                "stopped_at": (
                    item.stopped_at.isoformat()
                    if item.stopped_at
                    else None
                ),
                "status": item.status,
                "notes": item.notes,
                "recorded_at": item.recorded_at.isoformat(),
            }
            for item in medications
        ],
    }


# ============================================================
# SAFETY REVIEW REQUEST
# ============================================================


class SafetyReviewRequest(BaseModel):
    doctor_decision: str
    doctor_decision_notes: str | None = None


# ============================================================
# SAFETY ENGINE
# ============================================================


@app.post(
    "/doctor/patient/{patient_id}/safety-check",
)
def run_patient_safety_check(
    patient_id: int,
    data: SafetyCheckCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    patient = db.get(User, patient_id)

    if patient is None or patient.role != "Patient":
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    if not check_active_consent(
        db,
        doctor_id=current_user.id,
        patient_id=patient_id,
    ):
        raise HTTPException(
            status_code=403,
            detail="Active consent required",
        )

    prescription = get_prescription(
        db,
        data.prescription_id,
    )

    if prescription is None:
        raise HTTPException(
            status_code=404,
            detail="Prescription not found",
        )

    if (
        prescription.doctor_id != current_user.id
        or prescription.patient_id != patient_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Prescription does not belong to this doctor and patient",
        )

    if prescription.status != "Proposed":
        raise HTTPException(
            status_code=400,
            detail="Safety check can only be run on a Proposed prescription",
        )

    consultation = get_consultation(
        db,
        prescription.consultation_id,
    )

    if consultation is None:
        raise HTTPException(
            status_code=404,
            detail="Consultation not found",
        )

    prescription_items = get_prescription_items(
        db,
        prescription.id,
    )

    if not prescription_items:
        raise HTTPException(
            status_code=400,
            detail="Prescription has no medication items",
        )

    allergies = get_patient_allergies(
        db,
        patient_id,
    )

    conditions = get_patient_conditions(
        db,
        patient_id,
    )

    medications = get_patient_medications(
        db,
        patient_id,
    )

    findings = run_safety_engine(
        allergies=[
            {
                "allergen": item.allergen,
                "reaction": item.reaction,
                "severity": item.severity,
            }
            for item in allergies
        ],
        conditions=[
            {
                "condition_name": item.condition_name,
                "notes": item.notes,
            }
            for item in conditions
        ],
        current_medications=[
            {
                "medication_name": item.medication_name,
                "rxnorm_code": item.rxnorm_code,
                "dose": item.dose,
                "frequency": item.frequency,
                "status": item.status,
            }
            for item in medications
        ],
        prescription_items=[
            {
                "medication_name": item.medication_name,
                "rxnorm_code": item.rxnorm_code,
                "dose": item.dose,
                "frequency": item.frequency,
                "duration": item.duration,
                "instructions": item.instructions,
            }
            for item in prescription_items
        ],
    )
    ml_features = build_features(
        allergies=[{"allergen": item.allergen} for item in allergies],
        conditions=[{"condition_name": item.condition_name} for item in conditions],
        current_medications=[{"medication_name": item.medication_name, "status": item.status} for item in medications],
        prescription_items=[{"medication_name": item.medication_name, "dose": item.dose, "frequency": item.frequency} for item in prescription_items],
    )
    ml_review = predict_review_signal(ml_features)

    safety_check = create_safety_check(
        db=db,
        consultation_id=prescription.consultation_id,
        prescription_id=prescription.id,
        doctor_id=current_user.id,
        patient_id=patient_id,
        findings=findings,
    )

    create_audit_log(
        db=db,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="SAFETY_CHECK_PERFORMED",
        target_type="SafetyCheck",
        target_id=safety_check.id,
        description=(
            f"Safety check {safety_check.id} performed for "
            f"patient {patient_id} and prescription {prescription.id}."
        ),
    )

    return {
        "safety_check_id": safety_check.id,
        "consultation_id": safety_check.consultation_id,
        "prescription_id": prescription.id,
        "status": safety_check.status,
        "patient_id": patient.id,
        "patient_unique_id": patient.unique_user_id,
        "findings": [
            {
                "category": finding.category,
                "severity": finding.severity,
                "title": finding.title,
                "explanation": finding.explanation,
                "source": finding.source,
            }
            for finding in findings
        ],
        "doctor_final_decision_required": True,
        "ml_review": ml_review,
    }


# ============================================================
# SAFETY ENGINE — DOCTOR REVIEW
# ============================================================


@app.post(
    "/doctor/safety-check/{safety_check_id}/review",
)
def review_safety_check(
    safety_check_id: int,
    data: SafetyReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    safety_check = get_safety_check(
        db,
        safety_check_id,
    )

    if safety_check is None:
        raise HTTPException(
            status_code=404,
            detail="Safety check not found",
        )

    if safety_check.doctor_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to review this safety check",
        )

    if not check_active_consent(
        db, doctor_id=current_user.id, patient_id=safety_check.patient_id
    ):
        raise HTTPException(status_code=403, detail="Active consent required")

    if safety_check.status != "Pending Review":
        raise HTTPException(
            status_code=400,
            detail="Safety check has already been reviewed",
        )

    allowed_decisions = {
        "Approved",
        "Modified",
        "Rejected",
    }

    if data.doctor_decision not in allowed_decisions:
        raise HTTPException(
            status_code=400,
            detail="Invalid doctor decision",
        )

    safety_check.doctor_decision = data.doctor_decision
    safety_check.doctor_decision_notes = data.doctor_decision_notes
    safety_check.status = "Reviewed"

    db.commit()
    db.refresh(safety_check)

    create_audit_log(
        db=db,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="SAFETY_CHECK_REVIEWED",
        target_type="SafetyCheck",
        target_id=safety_check.id,
        description=(
            f"Doctor reviewed safety check {safety_check.id} "
            f"with decision {safety_check.doctor_decision}."
        ),
    )

    findings = get_safety_findings(
        db,
        safety_check.id,
    )

    return {
        "safety_check_id": safety_check.id,
        "patient_id": safety_check.patient_id,
        "status": safety_check.status,
        "doctor_decision": safety_check.doctor_decision,
        "doctor_decision_notes": safety_check.doctor_decision_notes,
        "findings": [
            {
                "category": finding.category,
                "severity": finding.severity,
                "title": finding.title,
                "explanation": finding.explanation,
                "source": finding.source,
            }
            for finding in findings
        ],
    }


class AccountActivationRequest(BaseModel):
    is_active: bool


@app.post("/admin/users/{user_id}/activation")
def set_account_activation(
    user_id: int,
    data: AccountActivationRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None or user.role not in {"Patient", "Doctor"}:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.status not in {"Active", "Deactivated"}:
        raise HTTPException(status_code=400, detail="Only approved accounts can be activated or deactivated")
    user.is_active = data.is_active
    user.status = "Active" if data.is_active else "Deactivated"
    db.commit()
    db.refresh(user)
    action = "ACCOUNT_ACTIVATED" if data.is_active else "ACCOUNT_DEACTIVATED"
    create_audit_log(
        db=db, actor_user_id=admin_user.id, actor_role="Admin", action=action,
        target_type="User", target_id=user.id,
        description=f"Admin {('activated' if data.is_active else 'deactivated')} {user.role} account {user.id}.",
    )
    return {"user_id": user.id, "status": user.status, "is_active": user.is_active}


@app.get("/auth/me")
def current_account(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "unique_user_id": current_user.unique_user_id,
        "email": current_user.email,
        "role": current_user.role,
        "status": current_user.status,
        "is_active": current_user.is_active,
    }
