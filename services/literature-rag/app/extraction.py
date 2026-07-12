from __future__ import annotations

import re
from typing import Any


ENTITY_PATTERNS: dict[str, dict[str, str]] = {
    "Polymer": {
        "polymer": r"\bpolymers?\b",
        "photoresist resin": r"\b(?:photoresist\s+)?resins?\b",
    },
    "PhotoacidGenerator": {
        "photoacid generator": r"\bphotoacid generators?\b|\bPAGs?\b",
    },
    "ProcessCondition": {
        "post exposure bake": r"\bpost[- ]exposure bake\b|\bPEB\b",
        "development": r"\bdevelop(?:ment|ing)?\b",
        "248 nm exposure": r"\b248\s*nm\b",
    },
    "LithographyMetric": {
        "critical dimension": r"\bcritical dimensions?\b|\bCD\b",
        "sensitivity": r"\bsensitivity\b",
        "resolution": r"\bresolution\b",
        "dissolution contrast": r"\bdissolution contrast\b",
    },
    "Method": {
        "chemically amplified resist": r"\bchemically amplified (?:resists?|photoresists?)\b",
        "KrF lithography": r"\bKrF\b",
    },
}


def extract_domain_entities(chunks: list[dict[str, Any]], document: dict[str, Any]) -> list[dict[str, Any]]:
    entities: dict[tuple[str, str], dict[str, Any]] = {}
    for chunk in chunks:
        for entity_type, patterns in ENTITY_PATTERNS.items():
            for label, pattern in patterns.items():
                if not re.search(pattern, chunk["text"], re.IGNORECASE):
                    continue
                key = (entity_type, label)
                entity = entities.setdefault(key, {
                    "id": f"{entity_type.lower()}:{label.replace(' ', '_')}",
                    "label": label,
                    "type": entity_type,
                    "document_id": document["document_id"],
                    "doi": document.get("doi"),
                    "chunk_ids": [],
                })
                entity["chunk_ids"].append(chunk["chunk_id"])
    return list(entities.values())
