from __future__ import annotations

import re


STOPWORDS = {
    "a", "an", "and", "are", "for", "from", "how", "is", "of", "the", "this", "to", "what", "which",
    "who", "whose", "why", "with", "does", "do", "can", "could", "please", "help", "find", "all",
    "about", "show", "search", "related",
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
    "光酸产生剂": ["photoacid", "generator", "pag"],
    "添加剂": ["additive"],
    "交联剂": ["crosslinker", "cross-linker", "crosslinking"],
    "抑制剂": ["inhibitor", "quencher", "acid", "trap"],
    "灵敏度": ["sensitivity"],
    "分辨率": ["resolution"],
    "曝光": ["exposure"],
    "显影": ["development", "developer"],
    "工艺": ["process", "processing", "lithography", "development", "bake"],
    "流程": ["process", "processing"],
    "优化": ["optimize", "optimization", "improve", "improvement", "strategy"],
    "改善": ["improve", "improvement", "enhance", "optimization"],
    "提升": ["improve", "improvement", "enhance", "increase"],
    "影响": ["effect", "influence", "impact", "affect"],
    "控制": ["control", "factor", "parameter"],
    "因素": ["factor", "parameter"],
    "线边粗糙度": ["line-edge", "line", "edge", "roughness", "ler"],
    "边缘粗糙度": ["line-edge", "line", "edge", "roughness", "ler"],
    "粗糙度": ["roughness", "ler", "line-edge", "line", "edge"],
    "粘度": ["viscosity"],
    "黏度": ["viscosity"],
    "溶解": ["dissolution"],
    "溶解度": ["dissolution", "solubility"],
    "对比度": ["contrast", "dissolution", "contrast"],
    "刻蚀": ["etch", "etching", "etch-resistant", "resistance"],
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
    "dissolution", "etch", "acid", "generator", "roughness", "ler", "line-edge", "process",
    "processing", "optimization", "optimize", "improve", "improvement", "contrast", "viscosity",
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

GRAPH_QUERY_SEPARATOR_PATTERN = re.compile(r"(?:\|\||\bOR\b|[，。！？；：、,/\\]+)", re.IGNORECASE)


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


def normalize_graph_query(question: str) -> str:
    """Normalize a graph query into space-separated search clauses."""
    text = str(question or "").strip()
    if not text:
        return ""
    text = GRAPH_QUERY_SEPARATOR_PATTERN.sub(" ", text)
    text = text.replace("|", " ")
    return re.sub(r"\s+", " ", text).strip()


def extract_graph_query_terms(question: str, max_terms: int = 32) -> list[str]:
    """Extract ordered graph-search terms with domain synonym expansion."""
    max_terms = max(1, int(max_terms or 12))
    normalized = normalize_graph_query(question)
    if not normalized:
        return []

    expanded = expand_query_text(normalized).lower()
    raw_tokens = re.findall(r"[a-z0-9][a-z0-9-]{1,}|[\u4e00-\u9fff]{2,}", expanded, re.IGNORECASE) or []
    terms: list[str] = []
    seen: set[str] = set()

    for token in raw_tokens:
        cleaned = token.strip().rstrip(".,?:;()[]{}")
        if not cleaned:
            continue
        if cleaned.isalpha() and cleaned in STOPWORDS:
            continue
        key = cleaned.lower()
        if key in seen or len(cleaned) < 2:
            continue
        seen.add(key)
        terms.append(cleaned)
        if len(terms) >= max_terms:
            break
    return terms


def has_domain_anchor(question: str) -> bool:
    return bool(tokenize_query(question) & DOMAIN_ANCHORS)
