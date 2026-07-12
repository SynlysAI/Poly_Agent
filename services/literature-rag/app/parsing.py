from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    position: int
    text: str


def clean_pdf_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.replace("\x00", "").splitlines()]
    counts = Counter(line for line in lines if 8 <= len(line) <= 120)
    repeated_headers = {line for line, count in counts.items() if count >= 2}
    kept: list[str] = []
    for line in lines:
        if not line or line in repeated_headers or re.fullmatch(r"(?:page\s*)?\d+", line, re.IGNORECASE):
            continue
        if re.fullmatch(r"references|bibliography", line, re.IGNORECASE):
            break
        if kept and kept[-1].endswith("-") and line[:1].islower():
            kept[-1] = kept[-1][:-1] + line
        else:
            kept.append(line)
    return "\n".join(kept).strip()


def chunk_text(text: str, *, chunk_size: int = 700, overlap: int = 100) -> list[TextChunk]:
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    tokens = text.split()
    if not tokens:
        return []
    chunks: list[TextChunk] = []
    step = chunk_size - overlap
    for position, start in enumerate(range(0, len(tokens), step)):
        chunk_tokens = tokens[start : start + chunk_size]
        if not chunk_tokens:
            break
        chunks.append(TextChunk(chunk_id=f"chunk_{position + 1:05d}", position=position, text=" ".join(chunk_tokens)))
        if start + chunk_size >= len(tokens):
            break
    return chunks
