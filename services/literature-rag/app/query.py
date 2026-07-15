from __future__ import annotations

import re


STOPWORDS = {
    "a", "an", "and", "are", "for", "from", "how", "is", "of", "the", "this", "to", "what", "which",
    "who", "whose", "why", "with", "does", "do", "can", "could", "please", "help", "find", "all",
}

DOMAIN_SYNONYMS = {
    "光刻胶": ["photoresist", "resist"],
    "光刻": ["lithography"],
    "文献": ["literature", "paper", "document"],
    "论文": ["paper", "literature", "document"],
    "文档": ["document", "paper", "literature"],
    "材料": ["material"],
    "树脂": ["resin"],
    "聚合物": ["polymer"],
    "酸": ["acid"],
    "光酸": ["photoacid"],
    "产酸剂": ["photoacid", "generator", "pag"],
    "灵敏度": ["sensitivity"],
    "分辨率": ["resolution"],
    "曝光": ["exposure"],
    "显影": ["development", "developer"],
    "焊接": ["welding", "weld", "joint", "arc", "laser", "friction", "stir"],
    "焊缝": ["weld", "joint", "nugget", "microstructure"],
    "稀土": ["rare", "earth", "rare-earth", "lanthanide"],
    "镧系": ["lanthanide", "rare", "earth"],
    "磁体": ["magnet", "magnetic"],
    "表面处理": ["surface", "treatment", "coating", "plasma", "corrosion"],
    "涂层": ["coating", "surface", "film"],
    "腐蚀": ["corrosion", "corrosion-resistant"],
    "等离子": ["plasma", "treatment"],
}

DOMAIN_ANCHORS = {
    "krf", "248", "photoresist", "resist", "lithography", "sensitivity", "resolution", "pag",
    "photoacid", "resin", "developer", "development", "exposure", "bake", "chemically", "amplified",
    "dissolution", "etch", "acid", "generator",
    "welding", "weld", "joint", "nugget", "arc", "laser", "friction", "stir", "microstructure",
    "rare", "earth", "rare-earth", "lanthanide", "magnet", "magnetic", "alloy", "catalyst",
    "surface", "treatment", "coating", "film", "plasma", "corrosion", "oxidation", "interface",
}

INVENTORY_PATTERNS = (
    r"全部.*(?:文档|文献|论文)",
    r"所有.*(?:文档|文献|论文)",
    r"(?:列出|找出|查看|显示).*(?:文档|文献|论文)",
    r"有哪些.*(?:文档|文献|论文)",
    r"\ball\s+(?:documents|papers|literature)\b",
    r"\blist\s+(?:documents|papers|literature)\b",
)


def is_document_inventory_query(question: str) -> bool:
    normalized = question.strip().lower()
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in INVENTORY_PATTERNS)


def expand_query_text(question: str) -> str:
    additions: list[str] = []
    for keyword, synonyms in DOMAIN_SYNONYMS.items():
        if keyword in question:
            additions.extend(synonyms)
    if re.search(r"\bkrf\b", question, re.IGNORECASE):
        additions.extend(["krf", "248", "photoresist", "lithography"])
    return f"{question} {' '.join(additions)}".strip()


def tokenize_query(question: str) -> set[str]:
    expanded = expand_query_text(question).lower()
    tokens = {item for item in re.findall(r"[a-z0-9][a-z0-9-]{1,}", expanded) if item not in STOPWORDS}
    return {item.rstrip(".,?:;()[]{}") for item in tokens if len(item.rstrip(".,?:;()[]{}")) > 1}


def has_domain_anchor(question: str) -> bool:
    return bool(tokenize_query(question) & DOMAIN_ANCHORS)
