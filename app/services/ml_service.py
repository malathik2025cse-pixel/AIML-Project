"""Doctor-facing review signal from a model trained on labelled synthetic data."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
import pandas as pd


ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "ml_artifacts"
MODEL_PATH = ARTIFACT_DIR / "review_model.joblib"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"
BACKGROUND_PATH = ARTIFACT_DIR / "shap_background.joblib"
FEATURES = ["current_medication_count", "condition_count", "allergy_match", "simvastatin_amlodipine", "simvastatin_over_20mg", "daily_frequency"]


def build_features(allergies: list[dict], conditions: list[dict], current_medications: list[dict], prescription_items: list[dict]) -> dict:
    current = {str(x.get("medication_name", "")).strip().casefold() for x in current_medications if str(x.get("status", "Active")).strip().casefold() == "active"}
    prescribed = {str(p.get("medication_name", "")).strip().casefold() for p in prescription_items}

    allergy_match = any(
        str(a.get("allergen", "")).strip().casefold() in str(p.get("medication_name", "")).strip().casefold()
        for a in allergies for p in prescription_items if a.get("allergen")
    )

    has_simva = "simvastatin" in prescribed or "simvastatin" in current
    has_amlo = "amlodipine" in prescribed or "amlodipine" in current
    at_least_one_prescribed = ("simvastatin" in prescribed) or ("amlodipine" in prescribed)
    simva_amlo = int(has_simva and has_amlo and at_least_one_prescribed)

    all_simva = (
        [p for p in prescription_items if str(p.get("medication_name", "")).strip().casefold() == "simvastatin"]
        + [m for m in current_medications if str(m.get("medication_name", "")).strip().casefold() == "simvastatin"]
    )
    doses = [float(m.group(1)) for p in all_simva if (m := re.search(r"(\d+(?:\.\d+)?)\s*mg\b", str(p.get("dose", "")), re.I))]

    return {
        "current_medication_count": len(current),
        "condition_count": len(conditions),
        "allergy_match": int(allergy_match),
        "simvastatin_amlodipine": simva_amlo,
        "simvastatin_over_20mg": int(any(d > 20 for d in doses)),
        "daily_frequency": int(any("daily" in str(p.get("frequency", "")).casefold() for p in prescription_items)),
    }


@lru_cache(maxsize=1)
def _load():
    import joblib
    if not MODEL_PATH.exists() or not METRICS_PATH.exists():
        return None
    with MODEL_PATH.open("rb") as f:
        model = joblib.load(f)
    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    background = joblib.load(BACKGROUND_PATH) if BACKGROUND_PATH.exists() else None
    return model, metrics, background


def predict_review_signal(features: dict) -> dict:
    loaded = _load()
    if loaded is None:
        return {"available": False, "review_recommended": None, "probability": None,
                "explanation": "The synthetic-data model has not been trained yet.", "model_version": None}
    model, metadata, background = loaded
    row = pd.DataFrame([{key: features[key] for key in FEATURES}], columns=FEATURES)
    probability = float(model.predict_proba(row)[0][1])
    signal = int(probability >= 0.5)
    explanations = []
    try:
        import shap
        estimator = model.named_steps["classifier"]
        matrix = model.named_steps["preprocessor"].transform(row)
        if hasattr(estimator, "estimators_"):
            values = shap.TreeExplainer(estimator)(matrix).values
            scores = values[0, :, 1] if values.ndim == 3 else values[0]
        elif background is not None:
            values = shap.LinearExplainer(estimator, background)(matrix).values
            scores = values[0]
        else:
            scores = []
        if len(scores):
            names = model.named_steps["preprocessor"].get_feature_names_out()
            explanations = [
                f"{str(names[i]).replace('numeric__', '').replace('binary__', '')} ({'raised' if scores[i] > 0 else 'lowered'} the model signal)"
                for i in sorted(range(len(scores)), key=lambda j: abs(scores[j]), reverse=True)[:3]
                if abs(scores[i]) > 1e-6
            ]
    except Exception:
        explanations = []
    if not explanations:
        explanations = [name for name in FEATURES if features[name]]
    if not explanations:
        explanations = ["No strong contributing feature was identified"]
    return {"available": True, "review_recommended": signal,
            "probability": round(probability, 4),
            "explanation": "Review signal reflects: " + ", ".join(explanations) + ". Trained and evaluated on synthetic demonstration data; not clinical evidence.",
            "model_name": metadata["selected_model"],
            "model_version": metadata.get("model_version", "1.0.0"),
            "dataset": metadata["dataset"]}
