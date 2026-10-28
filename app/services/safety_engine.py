import re
from dataclasses import dataclass


@dataclass
class SafetyFinding:
    category: str
    severity: str
    title: str
    explanation: str
    source: str


def _extract_mg_dose(dose: str | None) -> float | None:
    """
    Extract a numeric mg dose only when the dose contains
    an explicit numeric value followed by mg.
    """
    if not dose:
        return None

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*mg\b",
        str(dose).strip().lower(),
    )

    if match is None:
        return None

    return float(match.group(1))


def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"\s+", " ", str(name).strip().lower())


def _matches_allergy(allergen: str, medication_name: str) -> bool:
    norm_allergen = _normalize_name(allergen)
    norm_med = _normalize_name(medication_name)

    if not norm_allergen or not norm_med:
        return False

    if norm_allergen == norm_med:
        return True

    # Word boundary match (e.g., "penicillin" in "penicillin vk")
    if re.search(rf"\b{re.escape(norm_allergen)}\b", norm_med):
        return True

    # Substring match if allergen length is substantial (e.g. "amoxicillin" in "amoxicillin-clavulanate")
    if len(norm_allergen) >= 4 and (norm_allergen in norm_med or norm_med in norm_allergen):
        return True

    return False


def run_safety_engine(
    allergies: list[dict],
    conditions: list[dict],
    current_medications: list[dict],
    prescription_items: list[dict],
) -> list[SafetyFinding]:
    findings: list[SafetyFinding] = []
    seen_findings: set[tuple[str, str, str]] = set()

    # ---------------------------------------------------------
    # Rule A: Recorded allergy vs prescribed medication
    # ---------------------------------------------------------
    for prescribed in prescription_items:
        med_name = prescribed.get("medication_name", "")
        if not med_name:
            continue

        for allergy in allergies:
            allergen = allergy.get("allergen", "")
            if not allergen:
                continue

            if _matches_allergy(allergen, med_name):
                key = ("Allergy", _normalize_name(allergen), _normalize_name(med_name))
                if key in seen_findings:
                    continue
                seen_findings.add(key)

                findings.append(
                    SafetyFinding(
                        category="Allergy",
                        severity="High",
                        title="Potential allergy-related safety concern",
                        explanation=(
                            f"The prescribed medication ({med_name}) "
                            f"matches a recorded patient allergen ({allergen}). "
                            "Professional review is required."
                        ),
                        source="Patient allergy record",
                    )
                )

    # ---------------------------------------------------------
    # Rule B: Simvastatin + Amlodipine interaction
    # If the patient is taking or is prescribed both medications:
    # - Simvastatin > 20 mg/day: High
    # - Simvastatin <= 20 mg/day: Moderate
    # - Unknown or missing simvastatin dose: Moderate
    # ---------------------------------------------------------
    active_current = [
        m for m in current_medications
        if str(m.get("status", "Active")).lower() == "active"
    ]

    prescribed_simva = [
        p for p in prescription_items
        if _normalize_name(p.get("medication_name")) == "simvastatin"
    ]
    prescribed_amlo = [
        p for p in prescription_items
        if _normalize_name(p.get("medication_name")) == "amlodipine"
    ]

    current_simva = [
        m for m in active_current
        if _normalize_name(m.get("medication_name")) == "simvastatin"
    ]
    current_amlo = [
        m for m in active_current
        if _normalize_name(m.get("medication_name")) == "amlodipine"
    ]

    has_simvastatin = bool(prescribed_simva or current_simva)
    has_amlodipine = bool(prescribed_amlo or current_amlo)
    at_least_one_prescribed = bool(prescribed_simva or prescribed_amlo)

    if has_simvastatin and has_amlodipine and at_least_one_prescribed:
        # Determine simvastatin dose: prioritize prescribed order, then current record
        all_simva = prescribed_simva + current_simva
        extracted_doses = [
            _extract_mg_dose(item.get("dose"))
            for item in all_simva
            if item.get("dose") is not None
        ]
        valid_doses = [d for d in extracted_doses if d is not None]

        if any(d > 20 for d in valid_doses):
            max_dose = max(valid_doses)
            severity = "High"
            explanation = (
                "The patient is currently taking or prescribed amlodipine "
                f"and simvastatin at {max_dose:g} mg daily. "
                "Current prescribing information limits simvastatin to 20 mg "
                "daily when used with amlodipine. The prescription requires "
                "professional review."
            )
        elif valid_doses:
            dose_val = valid_doses[0]
            severity = "Moderate"
            explanation = (
                "The patient is currently taking or prescribed amlodipine "
                f"and simvastatin at {dose_val:g} mg daily. "
                "Amlodipine can increase simvastatin exposure, "
                "and the combination should be reviewed by the doctor."
            )
        else:
            severity = "Moderate"
            explanation = (
                "The patient is currently taking or prescribed amlodipine "
                "and simvastatin. The prescribed dose could not be reliably "
                "interpreted from the recorded dose format, so the combination "
                "requires professional review."
            )

        findings.append(
            SafetyFinding(
                category="Drug-Drug Interaction",
                severity=severity,
                title="Potential drug-drug interaction",
                explanation=explanation,
                source="FDA amlodipine prescribing information",
            )
        )

    return findings
