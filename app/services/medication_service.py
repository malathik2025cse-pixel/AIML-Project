from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen
import json
from urllib.error import URLError, HTTPError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.medication import MedicationReference


RXNORM_BASE_URL = "https://rxnav.nlm.nih.gov/REST"


def _get_json(url: str) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "MedShield/1.0",
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("RxNorm reference service is temporarily unavailable") from exc


def search_rxnorm(term: str, max_entries: int = 10) -> list[dict]:
    encoded_term = quote(term)

    url = (
        f"{RXNORM_BASE_URL}/approximateTerm.json"
        f"?term={encoded_term}"
        f"&maxEntries={max_entries}"
        f"&option=1"
    )

    data = _get_json(url)

    approximate_group = data.get("approximateGroup") or {}
    candidates = approximate_group.get("candidate") or []

    results = []

    for candidate in candidates:
        rxcui = candidate.get("rxcui")

        if not rxcui:
            continue

        results.append(
            {
                "rxcui": str(rxcui),
                "name": candidate.get("name") or "",
                "score": candidate.get("score"),
                "rank": candidate.get("rank"),
                "source": candidate.get("source"),
            }
        )

    return results


def get_rxnorm_properties(rxcui: str) -> dict | None:
    url = f"{RXNORM_BASE_URL}/rxcui/{quote(rxcui)}/properties.json"

    data = _get_json(url)

    properties = data.get("properties")

    if not properties:
        return None

    return {
        "rxcui": str(properties.get("rxcui")),
        "name": properties.get("name") or "",
        "synonym": properties.get("synonym"),
        "term_type": properties.get("tty"),
        "language": properties.get("language"),
        "suppress": properties.get("suppress"),
    }


def save_medication_reference(
    db: Session,
    rxcui: str,
    name: str,
    synonym: str | None,
    term_type: str | None,
    source: str | None,
) -> MedicationReference:
    medication = db.scalar(
        select(MedicationReference).where(
            MedicationReference.rxcui == rxcui
        )
    )

    if medication is None:
        medication = MedicationReference(
            rxcui=rxcui,
            name=name,
            synonym=synonym,
            term_type=term_type,
            source=source,
        )
        db.add(medication)
    else:
        medication.name = name
        medication.synonym = synonym
        medication.term_type = term_type
        medication.source = source
        medication.last_verified_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(medication)

    return medication


def search_and_store_medications(
    db: Session,
    term: str,
) -> list[dict]:
    candidates = search_rxnorm(term)

    results = []
    seen_rxcuis = set()

    for candidate in candidates:
        rxcui = candidate["rxcui"]

        if rxcui in seen_rxcuis:
            continue

        seen_rxcuis.add(rxcui)

        properties = get_rxnorm_properties(rxcui)

        if properties is None:
            continue

        medication = save_medication_reference(
            db=db,
            rxcui=properties["rxcui"],
            name=properties["name"],
            synonym=properties["synonym"],
            term_type=properties["term_type"],
            source="RXNORM",
        )

        results.append(
            {
                "id": medication.id,
                "rxcui": medication.rxcui,
                "name": medication.name,
                "synonym": medication.synonym,
                "term_type": medication.term_type,
                "source": medication.source,
                "match_score": candidate.get("score"),
                "match_rank": candidate.get("rank"),
            }
        )

    return results
