"""JD keyword extraction and coverage, so a tailored resume speaks the JD's language.

Honesty rule: a keyword is only ever surfaced if it is already true of the
resume (a skill, a bullet, a tag). Keywords the JD wants that the resume does
not show are reported as GAPS, never inserted.
"""
import re

# canonical term -> regex of ways a JD may write it
VOCAB = {
    "Python": r"python", "SQL": r"\bsql\b", "Django": r"django", "Flask": r"flask", "FastAPI": r"fastapi",
    "REST APIs": r"rest(?:ful)?(?:\s+apis?)?\b|\bapis?\b", "OAuth2": r"oauth2?", "Webhooks": r"webhooks?",
    "CI/CD": r"ci\s*/\s*cd|continuous (?:integration|delivery|deployment)", "Docker": r"docker|containers?",
    "Kubernetes": r"kubernetes|\bk8s\b", "AWS": r"\baws\b|amazon web services", "GCP": r"\bgcp\b|google cloud",
    "Azure": r"azure", "PostgreSQL": r"postgres(?:ql)?", "MySQL": r"mysql", "MongoDB": r"mongo(?:db)?",
    "Redis": r"redis", "Kafka": r"kafka", "Git": r"\bgit\b", "Linux": r"linux",
    "LLMs": r"\bllms?\b|large language models?", "RAG": r"\brag\b|retrieval[- ]augmented",
    "Llama": r"llama", "vLLM": r"vllm", "Qdrant": r"qdrant", "Embeddings": r"embeddings?",
    "Vector databases": r"vector (?:db|databases?|stores?|search)|qdrant|pinecone|weaviate|milvus|pgvector", "NLP": r"\bnlp\b|natural language",
    "PyTorch": r"pytorch", "TensorFlow": r"tensorflow", "Transformers": r"transformers?",
    "Machine learning": r"machine learning|\bml\b", "Deep learning": r"deep learning",
    "Fine-tuning": r"fine[- ]?tun", "Prompt engineering": r"prompt engineering", "Quantisation": r"quantis|quantiz",
    "GPU": r"\bgpus?\b|cuda", "Anthropic API": r"anthropic", "Microservices": r"micro-?services?",
    "Automation": r"automat", "Data pipelines": r"data pipelines?|\betl\b", "Testing": r"unit test|pytest|test[- ]driven",
    "Performance optimisation": r"performance|optimi[sz]",
}
_COMPILED = {k: re.compile(v, re.I) for k, v in VOCAB.items()}


def jd_keywords(jd: str, resume: dict | None = None) -> list[str]:
    """Canonical keywords found in the JD, most frequent first. Any skill named
    in the resume is also searched for literally, so custom skills work."""
    found = {}
    for k, rx in _COMPILED.items():
        n = len(rx.findall(jd))
        if n:
            found[k] = n
    if resume:
        for group in resume["skills"].values():
            for s in group:
                if s in found or any(s.lower() == k.lower() for k in found):
                    continue
                n = len(re.findall(rf"(?<![\w+#]){re.escape(s)}(?![\w+#])", jd, re.I))
                if n:
                    found[s] = n
    return sorted(found, key=lambda k: -found[k])


def present_in(keyword: str, text: str) -> bool:
    rx = _COMPILED.get(keyword)
    if rx:
        return bool(rx.search(text))
    return bool(re.search(rf"(?<![\w+#]){re.escape(keyword)}(?![\w+#])", text, re.I))


def resume_text(resume: dict, tailored: dict | None = None) -> str:
    """Text of the resume as rendered (tailored) or as a whole (tailored=None)."""
    parts = [resume["summary"] if tailored is None else tailored["summary"]]
    parts += [s for g in resume["skills"].values() for s in g]
    for role in resume["experience"]:
        parts.append(role["title"])
        chosen = None if tailored is None else next(
            (r["bullet_ids"] for r in tailored["experience"] if r["id"] == role["id"]), [])
        parts += [b["text"] for b in role["bullets"] if chosen is None or b["id"] in chosen]
    parts += [f'{p["name"]} {p["text"]}' for p in resume.get("projects") or []]
    parts += resume.get("certifications", []) + resume.get("extras", [])
    return "\n".join(parts)


def coverage(resume: dict, tailored: dict, keywords: list[str]) -> dict:
    shown = resume_text(resume, tailored)
    whole = resume_text(resume)
    covered = [k for k in keywords if present_in(k, shown)]
    return {"covered": covered,
            "unplaced": [k for k in keywords if k not in covered and present_in(k, whole)],
            "gaps": [k for k in keywords if not present_in(k, whole)]}


def cover_more(resume: dict, tailored: dict, keywords: list[str], max_bullets: int) -> None:
    """Greedily add resume bullets that bring in JD keywords not yet shown."""
    for _ in range(len(keywords)):
        cov = coverage(resume, tailored, keywords)
        if not cov["unplaced"]:
            return
        best = None
        for role in resume["experience"]:
            item = next(r for r in tailored["experience"] if r["id"] == role["id"])
            if len(item["bullet_ids"]) >= max_bullets:
                continue
            for b in role["bullets"]:
                if b["id"] in item["bullet_ids"]:
                    continue
                gain = sum(present_in(k, b["text"]) for k in cov["unplaced"])
                if gain and (best is None or gain > best[0]):
                    best = (gain, item, b["id"], role)
        if not best:
            return
        _, item, bid, role = best
        item["bullet_ids"].append(bid)
        item["bullet_ids"].sort(key=lambda i: [b["id"] for b in role["bullets"]].index(i))
