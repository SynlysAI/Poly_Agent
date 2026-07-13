from __future__ import annotations

import json
from typing import Any


class OpenAIAnswerGenerator:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key or "EMPTY", base_url=base_url or None)
        self.model = model

    def __call__(self, question: str, hits: list[dict[str, Any]]) -> str:
        evidence = "\n\n".join(
            f"[{index}] DOI={item.get('doi')} chunk={item.get('chunk_id')}\n{item.get('text')}"
            for index, item in enumerate(hits, start=1)
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": (
                    "Answer only from the supplied evidence. Cite claims with [n]. "
                    "If evidence is insufficient, say so explicitly. Never invent a paper or DOI."
                )},
                {"role": "user", "content": f"Question:\n{question}\n\nEvidence:\n{evidence}"},
            ],
            temperature=0.1,
        )
        return (response.choices[0].message.content or "").strip()


class OpenAIEntityExtractor:
    ALLOWED_TYPES = {
        "Resin", "Polymer", "Monomer", "PhotoacidGenerator", "Additive",
        "ProcessCondition", "LithographyMetric", "Property", "Method",
    }

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key or "EMPTY", base_url=base_url or None)
        self.model = model

    def __call__(self, chunks: list[dict[str, Any]], document: dict[str, Any]) -> list[dict[str, Any]]:
        text = "\n\n".join(f"{item['chunk_id']}: {item['text']}" for item in chunks[:20])
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": (
                    "Extract a KrF/248 nm photoresist knowledge graph from the supplied chunks only. "
                    "Return a JSON object: {\"entities\":[{\"label\":string,\"type\":string,\"chunk_ids\":[string]}]}. "
                    f"Allowed types: {sorted(self.ALLOWED_TYPES)}. "
                    "Classify materials/resist components as Resin/Polymer/Monomer/PhotoacidGenerator/Additive; "
                    "process or formulation approaches as Method/Strategy/ProcessCondition; measured or target "
                    "outcomes as LithographyMetric/Property. Use exact concise labels from the text where possible, "
                    "such as PVP, PMMA, methacrylate terpolymer, phenolic resin, PAG, acid trap reagent, post exposure "
                    "bake, 248 nm exposure, resolution, sensitivity, exposure latitude, dissolution contrast, "
                    "etch resistance. Do not invent entities, values, DOIs, or chunk IDs. Use only supplied chunk IDs. "
                    "Merge duplicates by normalized label and type."
                )},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"}, temperature=0,
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        valid_chunk_ids = {item["chunk_id"] for item in chunks}
        entities = []
        for item in payload.get("entities") or []:
            label = str(item.get("label") or "").strip()
            entity_type = str(item.get("type") or "")
            chunk_ids = [value for value in item.get("chunk_ids") or [] if value in valid_chunk_ids]
            if not label or entity_type not in self.ALLOWED_TYPES or not chunk_ids:
                continue
            entities.append({
                "id": f"{entity_type.lower()}:{label.lower().replace(' ', '_')}",
                "label": label, "type": entity_type, "document_id": document["document_id"],
                "doi": document.get("doi"), "chunk_ids": chunk_ids,
            })
        return entities
