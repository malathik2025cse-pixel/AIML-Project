from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _check_bcrypt_password_length(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be no more than 72 UTF-8 bytes")
    return value


# ============================================================
# LOGIN
# ============================================================

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    _password_length = field_validator("password")(_check_bcrypt_password_length)



# ============================================================
# ADMIN LOGIN
# ============================================================

class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str

    _password_length = field_validator("password")(_check_bcrypt_password_length)



# ============================================================
# PATIENT / DOCTOR REGISTRATION
# ============================================================

class RegistrationRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: str

    _password_length = field_validator("password")(_check_bcrypt_password_length)

    # Doctor verification information
    medical_registration_number: str | None = None
    registration_authority: str | None = None
    qualification: str | None = None
    specialization: str | None = None
    years_of_practice: int | None = None
    hospital_clinic: str | None = None



# ============================================================
# ACCOUNT STATUS
# ============================================================

class AccountStatusResponse(BaseModel):
    email: EmailStr
    role: str
    status: str
    is_active: bool
    unique_user_id: str | None = None



# ============================================================
# CONSENT
# ============================================================

class ConsentRequestCreate(BaseModel):
    patient_unique_id: str



class ConsentRequestResponse(BaseModel):
    id: int
    doctor_id: int
    patient_id: int
    status: str
    requested_at: str
    responded_at: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None
    doctor_unique_id: str | None = None
    patient_unique_id: str | None = None



# ============================================================
# MEDICAL RECORD
# ============================================================

class MedicalRecordCreate(BaseModel):

    blood_group: str | None = None
    allergies: str | None = None
    medical_conditions: str | None = None
    current_medications: str | None = None



class MedicalRecordResponse(BaseModel):

    id: int
    patient_id: int
    blood_group: str | None
    allergies: str | None
    medical_conditions: str | None
    current_medications: str | None


    model_config = ConfigDict(from_attributes=True)

class ConsultationCreate(BaseModel):
    patient_id: int | None = None
    reason_for_visit: str = Field(min_length=1)
    clinical_notes: str | None = None
    assessment: str | None = None


class ConsultationResponse(BaseModel):
    id: int
    doctor_id: int
    patient_id: int
    started_at: str
    reason_for_visit: str
    clinical_notes: str | None = None
    assessment: str | None = None
    status: str

class PrescriptionItemCreate(BaseModel):
    medication_name: str = Field(min_length=1)
    rxnorm_code: str | None = None
    dose: str = Field(min_length=1)
    frequency: str = Field(min_length=1)
    duration: str = Field(min_length=1)
    instructions: str | None = None


class PrescriptionCreate(BaseModel):
    consultation_id: int
    patient_id: int
    doctor_notes: str | None = None
    items: list[PrescriptionItemCreate]
    
class SafetyCheckCreate(BaseModel):
    prescription_id: int


class PrescriptionItemResponse(BaseModel):
    id: int
    prescription_id: int
    medication_name: str
    rxnorm_code: str | None = None
    dose: str
    frequency: str
    duration: str
    instructions: str | None = None


class PrescriptionResponse(BaseModel):
    id: int
    consultation_id: int
    doctor_id: int
    patient_id: int
    prescribed_at: str
    status: str
    doctor_notes: str | None = None
    items: list[PrescriptionItemResponse]

class MedicationSearchResponse(BaseModel):
    id: int
    rxcui: str
    name: str
    synonym: str | None = None
    term_type: str | None = None
    source: str | None = None
    match_score: float | None = None
    match_rank: int | None = None

class AllergyCreate(BaseModel):
    allergen: str
    reaction: str | None = None
    severity: str | None = None


class AllergyResponse(BaseModel):
    id: int
    patient_id: int
    allergen: str
    reaction: str | None = None
    severity: str | None = None
    recorded_at: str


class MedicalConditionCreate(BaseModel):
    condition_name: str
    notes: str | None = None


class MedicalConditionResponse(BaseModel):
    id: int
    patient_id: int
    condition_name: str
    notes: str | None = None
    recorded_at: str


class PatientMedicationCreate(BaseModel):
    medication_name: str
    rxnorm_code: str | None = None
    dose: str | None = None
    frequency: str | None = None
    started_at: str | None = None
    notes: str | None = None


class PatientMedicationResponse(BaseModel):
    id: int
    patient_id: int
    medication_name: str
    rxnorm_code: str | None = None
    dose: str | None = None
    frequency: str | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    status: str
    notes: str | None = None
    recorded_at: str
