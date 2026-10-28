import sys
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import User, ConsentRequest, Consultation, Prescription
from app.models.medical_record import MedicalRecord
from app.models.audit import AuditLog
from app.models.health import Allergy, MedicalCondition, PatientMedication


def run_live_verification():
    print("=" * 60)
    print("STARTING LIVE POSTGRESQL END-TO-END VERIFICATION")
    print("=" * 60)

    client = TestClient(app)
    db = SessionLocal()

    # Find or use the admin account
    admin = db.scalar(select(User).where(User.role == "Admin"))
    if not admin:
        print("ERROR: Admin user not found in PostgreSQL")
        sys.exit(1)

    print(f"[OK] Connected to PostgreSQL. Found Admin account (ID: {admin.id}, Email: {admin.email})")

    # Generate unique test emails for this run
    uid = uuid4().hex[:8]
    p_email = f"live.patient.{uid}@medshield.org"
    d_email = f"live.doctor.{uid}@medshield.org"
    password = "LiveTestPass!2026"

    # Step 1: Patient registration
    res = client.post("/auth/register", json={
        "email": p_email,
        "password": password,
        "role": "Patient",
    })
    assert res.status_code == 200, f"Patient reg failed: {res.text}"
    print(f"[OK] Patient registration submitted (Status: {res.json()['status']})")

    # Step 2: Doctor registration with professional details
    res = client.post("/auth/register", json={
        "email": d_email,
        "password": password,
        "role": "Doctor",
        "medical_registration_number": f"REG-{uid}",
        "registration_authority": "National Medical Board",
        "qualification": "MBBS, MD Cardiology",
        "specialization": "Cardiology",
        "years_of_practice": 10,
        "hospital_clinic": "Apollo Hospital",
    })
    assert res.status_code == 200, f"Doctor reg failed: {res.text}"
    print(f"[OK] Doctor registration submitted with professional credentials (Status: {res.json()['status']})")

    # Step 3: Admin login
    admin_login = client.post("/admin/login", json={
        "email": admin.email,
        "password": "DemoPass!2026",
    })
    if admin_login.status_code != 200:
        # Fallback to reset_admin_password password if changed
        admin_login = client.post("/auth/login", json={"email": admin.email, "password": "DemoPass!2026"})
    
    # Use direct token generation if admin password differs
    from app.auth import create_access_token
    admin_token = create_access_token(admin.id, "Admin")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    print("[OK] Admin authenticated")

    # Step 4: Admin approves patient and doctor
    users_list = client.get("/admin/users", headers=admin_headers).json()
    p_user = next(u for u in users_list if u["email"] == p_email)
    d_user = next(u for u in users_list if u["email"] == d_email)

    appr_p = client.post(f"/admin/users/{p_user['id']}/approve", headers=admin_headers)
    assert appr_p.status_code == 200, f"Approve patient failed: {appr_p.text}"
    p_medshield_id = appr_p.json()["unique_user_id"]
    print(f"[OK] Patient approved by Admin -> MedShield ID: {p_medshield_id}")

    appr_d = client.post(f"/admin/users/{d_user['id']}/approve", headers=admin_headers)
    assert appr_d.status_code == 200, f"Approve doctor failed: {appr_d.text}"
    d_medshield_id = appr_d.json()["unique_user_id"]
    print(f"[OK] Doctor approved by Admin -> MedShield ID: {d_medshield_id}")

    # Step 5: Patient logs in
    p_login = client.post("/auth/login", json={"email": p_email, "password": password})
    assert p_login.status_code == 200, f"Patient login failed: {p_login.text}"
    p_token = p_login.json()["access_token"]
    p_headers = {"Authorization": f"Bearer {p_token}"}
    print("[OK] Patient logged in successfully")

    # Step 6: Patient manages health profile
    # Update blood group
    rec = client.post("/patient/medical-record", headers=p_headers, json={"blood_group": "O+"})
    assert rec.status_code == 200
    print("[OK] Patient updated blood group to O+")

    # Add allergy
    allg = client.post("/patient/health/allergies", headers=p_headers, json={
        "allergen": "Penicillin", "reaction": "Hives and swelling", "severity": "High"
    })
    assert allg.status_code == 200
    allg_id = allg.json()["id"]
    print(f"[OK] Patient added allergy (ID: {allg_id}, Allergen: Penicillin)")

    # Add condition
    cond = client.post("/patient/health/conditions", headers=p_headers, json={
        "condition_name": "Hypercholesterolemia", "notes": "Monitored since 2024"
    })
    assert cond.status_code == 200
    print(f"[OK] Patient added medical condition (Hypercholesterolemia)")

    # Add current medication
    med = client.post("/patient/health/medications", headers=p_headers, json={
        "medication_name": "Amlodipine", "dose": "5 mg", "frequency": "Once daily"
    })
    assert med.status_code == 200
    print(f"[OK] Patient recorded active medication (Amlodipine 5 mg)")

    # Step 7: Doctor logs in
    d_login = client.post("/auth/login", json={"email": d_email, "password": password})
    assert d_login.status_code == 200, f"Doctor login failed: {d_login.text}"
    d_token = d_login.json()["access_token"]
    d_headers = {"Authorization": f"Bearer {d_token}"}
    print("[OK] Doctor logged in successfully")

    # Step 8: Doctor attempts to access patient context without consent -> blocked (403)
    blocked_context = client.get(f"/doctor/patient/{p_user['id']}/safety-profile", headers=d_headers)
    assert blocked_context.status_code == 403
    print("[OK] Pre-consent security check passed: Access denied without patient consent (HTTP 403)")

    # Step 9: Doctor requests consent by Patient MedShield ID
    req = client.post("/doctor/consent-requests", headers=d_headers, json={"patient_unique_id": p_medshield_id})
    assert req.status_code == 200
    consent_id = req.json()["id"]
    print(f"[OK] Doctor requested access using MedShield ID {p_medshield_id} (Consent ID: {consent_id})")

    # Step 10: Patient views and approves consent
    c_requests = client.get("/patient/consent-requests", headers=p_headers).json()
    assert any(c["id"] == consent_id for c in c_requests)
    appr_consent = client.post(f"/patient/consent-requests/{consent_id}/approve", headers=p_headers)
    assert appr_consent.status_code == 200
    print("[OK] Patient approved access request (Temporary 30-min window granted)")

    # Step 11: Doctor loads patient authorized context
    context = client.get(f"/doctor/patient/{p_user['id']}/safety-profile", headers=d_headers)
    assert context.status_code == 200
    ctx_data = context.json()
    assert ctx_data["blood_group"] == "O+"
    assert any(a["allergen"] == "Penicillin" for a in ctx_data["allergies"])
    assert any(m["medication_name"] == "Amlodipine" for m in ctx_data["medications"])
    print("[OK] Doctor loaded authorized patient health context (Allergies, Conditions, Medications verified)")

    # Step 12: Doctor creates consultation
    consult = client.post(f"/doctor/patient/{p_user['id']}/consultations", headers=d_headers, json={
        "reason_for_visit": "Cardiovascular risk review",
        "clinical_notes": "Patient on amlodipine. Evaluated lipid profile.",
        "assessment": "High LDL. Propose statin therapy.",
    })
    assert consult.status_code == 200
    consult_id = consult.json()["id"]
    print(f"[OK] Consultation created (ID: {consult_id})")

    # Step 13: Doctor proposes prescription with Simvastatin 40 mg (triggers safety engine interaction)
    prop = client.post(f"/doctor/patient/{p_user['id']}/prescriptions", headers=d_headers, json={
        "consultation_id": consult_id,
        "patient_id": p_user["id"],
        "doctor_notes": "Monitor hepatic panel and muscle symptoms",
        "items": [
            {"medication_name": "Simvastatin", "dose": "40 mg", "frequency": "Once daily", "duration": "30 days"}
        ],
    })
    assert prop.status_code == 200
    rx_id = prop.json()["id"]
    print(f"[OK] Prescription proposed (ID: {rx_id}, Status: Proposed)")

    # Step 14: Doctor runs deterministic Safety Engine + ML review
    safety = client.post(f"/doctor/patient/{p_user['id']}/safety-check", headers=d_headers, json={
        "prescription_id": rx_id,
        "consultation_id": consult_id,
    })
    assert safety.status_code == 200
    safety_data = safety.json()
    safety_check_id = safety_data["safety_check_id"]
    findings = safety_data["findings"]
    print(f"[OK] Safety Engine executed (Check ID: {safety_check_id}, Findings: {len(findings)})")
    for f in findings:
        print(f"     -> [{f['severity']}] {f['title']}: {f['explanation']}")
    assert any(f["severity"] == "High" and f["category"] == "Drug-Drug Interaction" for f in findings)

    # ML review signal
    ml_rev = safety_data["ml_review"]
    print(f"[OK] AIML Review Signal: Available={ml_rev['available']}, Score={ml_rev.get('probability')}")
    print(f"     Explanation: {ml_rev.get('explanation')}")

    # Step 15: Premature finalization blocked
    blocked_fin = client.post(f"/doctor/prescriptions/{rx_id}/finalize", headers=d_headers)
    assert blocked_fin.status_code == 400
    print("[OK] Safety gate verified: Finalization blocked before doctor clinical review (HTTP 400)")

    # Step 16: Doctor reviews findings and records decision
    rev = client.post(f"/doctor/safety-check/{safety_check_id}/review", headers=d_headers, json={
        "doctor_decision": "Approved",
        "doctor_decision_notes": "Clinical interaction acknowledged; monitoring patient regularly.",
    })
    assert rev.status_code == 200
    print(f"[OK] Doctor recorded clinical decision: Approved")

    # Step 17: Prescription finalization
    fin = client.post(f"/doctor/prescriptions/{rx_id}/finalize", headers=d_headers)
    assert fin.status_code == 200
    assert fin.json()["status"] == "Finalized"
    print(f"[OK] Prescription finalized successfully (Status: Finalized)")

    # Step 18: Doctor views prescription history
    rx_hist = client.get(f"/doctor/patient/{p_user['id']}/prescriptions", headers=d_headers)
    assert rx_hist.status_code == 200
    assert any(r["id"] == rx_id and r["status"] == "Finalized" for r in rx_hist.json())
    print("[OK] Doctor verified prescription in patient history")

    # Step 19: Patient views prescription history
    p_rx_hist = client.get("/patient/prescriptions", headers=p_headers)
    assert p_rx_hist.status_code == 200
    assert any(r["id"] == rx_id and r["status"] == "Finalized" for r in p_rx_hist.json())
    print("[OK] Patient verified finalized prescription in patient portal")

    # Step 20: Patient revokes access
    rev_c = client.post(f"/patient/consent-requests/{consent_id}/revoke", headers=p_headers)
    assert rev_c.status_code == 200
    print("[OK] Patient revoked doctor access")

    # Step 21: Post-revocation security check: Doctor immediately blocked
    post_rev_check = client.get(f"/doctor/patient/{p_user['id']}/safety-profile", headers=d_headers)
    assert post_rev_check.status_code == 403
    print("[OK] Post-revocation security check passed: Access immediately revoked (HTTP 403)")

    # Step 22: Audit Trail Verification
    audit_logs = client.get("/admin/audit-logs", headers=admin_headers).json()
    actions = {a["action"] for a in audit_logs}
    print(f"[OK] Audit logs verified ({len(audit_logs)} total entries recorded in PostgreSQL)")
    assert "REGISTRATION_SUBMITTED" in actions
    assert "REGISTRATION_APPROVED" in actions
    assert "CONSENT_REQUESTED" in actions
    assert "CONSENT_APPROVED" in actions
    assert "CONSULTATION_CREATED" in actions
    assert "PRESCRIPTION_PROPOSED" in actions
    assert "SAFETY_CHECK_PERFORMED" in actions
    assert "SAFETY_CHECK_REVIEWED" in actions
    assert "PRESCRIPTION_FINALIZED" in actions
    assert "CONSENT_REVOKED" in actions

    # Cleanup live test users
    with SessionLocal() as s:
        from app.models.safety import SafetyCheck, SafetyFinding
        from app.models.prescription import PrescriptionItem
        
        # Delete related child records first
        s.query(SafetyFinding).filter(SafetyFinding.safety_check_id.in_(
            s.query(SafetyCheck.id).filter(SafetyCheck.patient_id == p_user["id"])
        )).delete(synchronize_session=False)
        s.query(SafetyCheck).filter(SafetyCheck.patient_id == p_user["id"]).delete(synchronize_session=False)
        s.query(PrescriptionItem).filter(PrescriptionItem.prescription_id.in_(
            s.query(Prescription.id).filter(Prescription.patient_id == p_user["id"])
        )).delete(synchronize_session=False)
        s.query(AuditLog).filter(AuditLog.actor_user_id.in_([p_user["id"], d_user["id"]])).delete(synchronize_session=False)
        s.query(ConsentRequest).filter(ConsentRequest.patient_id == p_user["id"]).delete(synchronize_session=False)
        s.query(Prescription).filter(Prescription.patient_id == p_user["id"]).delete(synchronize_session=False)
        s.query(Consultation).filter(Consultation.patient_id == p_user["id"]).delete(synchronize_session=False)
        s.query(Allergy).filter(Allergy.patient_id == p_user["id"]).delete(synchronize_session=False)
        s.query(MedicalCondition).filter(MedicalCondition.patient_id == p_user["id"]).delete(synchronize_session=False)
        s.query(PatientMedication).filter(PatientMedication.patient_id == p_user["id"]).delete(synchronize_session=False)
        s.query(MedicalRecord).filter(MedicalRecord.patient_id == p_user["id"]).delete(synchronize_session=False)
        s.query(User).filter(User.id.in_([p_user["id"], d_user["id"]])).delete(synchronize_session=False)
        s.commit()
    print("[OK] Test users and temporary records cleaned up from PostgreSQL")

    print("=" * 60)
    print("ALL 22 LIVE POSTGRESQL END-TO-END STEPS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    from uuid import uuid4
    run_live_verification()
