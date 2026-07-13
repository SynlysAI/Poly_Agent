from __future__ import annotations

import re
from typing import Any


ENTITY_PATTERNS: dict[str, dict[str, str]] = {
    "Resin": {
        "photoresist resin": r"\b(?:photoresist\s+)?resins?\b",
        "phenolic resin": r"\bphenolic resins?\b",
        "novolak resin": r"\bnovola[ck] resins?\b",
    },
    "Polymer": {
        "polymer": r"\bpolymers?\b",
        "PVP": r"\bPVP\b|\bpoly\s*\(\s*vinyl\s+phenol\s*\)\b",
        "PMMA": r"\bPMMA\b|\bpoly\s*\(\s*methyl\s+methacrylate\s*\)\b",
        "methacrylate polymer": r"\bmethacrylate (?:ter)?polymers?\b|\bMMA[-\s]TBMA[-\s]MAA\b",
        "vinylphenol methacrylate copolymer": r"\bvinylphenol[-\s].*?methacrylate copolymers?\b|\bVP[-\s]EAdMA\b",
    },
    "Monomer": {
        "tert-butyl acrylate": r"\btert[-\s]?butyl acrylate\b|\btBA\b",
        "acetoxystyrene": r"\b4[-\s]?acetoxystyrene\b|\bStyOAc\b",
    },
    "PhotoacidGenerator": {
        "photoacid generator": r"\bphotoacid generators?\b|\bPAGs?\b",
    },
    "Additive": {
        "acid trap reagent": r"\bacid trap reagents?\b",
        "dissolution inhibitor": r"\bdissolution inhibitors?\b",
        "adamantyl protective group": r"\badamantyl protective groups?\b|\b2[-\s]alkyl[-\s]2[-\s]adamantyl\b",
    },
    "ProcessCondition": {
        "post exposure bake": r"\bpost[- ]exposure bake\b|\bPEB\b",
        "development": r"\bdevelop(?:ment|ing)?\b",
        "248 nm exposure": r"\b248\s*nm\b",
        "exposure latitude": r"\bexposure latitude\b",
        "depth of focus": r"\bdepth of focus\b|\bDOF\b",
        "oxygen addition": r"\boxygen addition\b",
    },
    "LithographyMetric": {
        "critical dimension": r"\bcritical dimensions?\b|\bCD\b",
        "sensitivity": r"\bsensitivity\b",
        "resolution": r"\bresolution\b",
        "dissolution contrast": r"\bdissolution contrast\b",
        "etch resistance": r"\betch[- ]resistan(?:t|ce)\b|\bdry[- ]etch resistance\b",
        "lithographic performance": r"\blithographic performance\b",
    },
    "Method": {
        "chemically amplified resist": r"\bchemically amplified (?:resists?|photoresists?)\b",
        "KrF lithography": r"\bKrF\b",
        "tri-level resist process": r"\btri[- ]level resist process\b",
        "acid trap soaking": r"\bacid trap reagent soaking\b",
        "RAFT polymerization": r"\breversible addition fragmentation chain transfer\b|\bRAFT\b",
    },
    "Strategy": {
        "single layer resist": r"\bsingle layer resists?\b",
        "pattern profile improvement": r"\bpattern profile improvement\b",
        "resist removal": r"\bphotoresist removal\b|\bresist removal\b",
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
