import json

from openai import AzureOpenAI

from config import settings
from search_service import search

_client = AzureOpenAI(
    azure_endpoint=settings.openai_endpoint,
    api_key=settings.openai_key,
    api_version=settings.openai_api_version,
    timeout=60,
    max_retries=4,
)

SUMMARY_PROMPT = """You get work-experience excerpts from several CVs, grouped by file name.
Return ONLY JSON: {"summaries": {"<file_name>": "<2 short sentences>"}}.
Summarize each candidate's professional experience using ONLY their own excerpts. Never invent anything.
If the excerpts say nothing about experience, write "Not stated in the CV".
Write in the requested language."""


def compare_table(files: list[str], profiles: list[dict]) -> dict:
    """Deterministic comparison from structured profiles (no GPT, no hallucination).
    Returns rows (one per candidate) + common skills + skills unique to each candidate."""
    by_file = {p["file_name"]: p for p in profiles}
    chosen = [by_file[f] for f in files if f in by_file]

    skill_sets = {p["file_name"]: set(p.get("skills") or []) for p in chosen}
    common = set.intersection(*skill_sets.values()) if skill_sets else set()

    rows, unique = [], {}
    for p in chosen:
        f = p["file_name"]
        others = set().union(*(s for k, s in skill_sets.items() if k != f)) if len(skill_sets) > 1 else set()
        unique[f] = sorted(skill_sets[f] - others)
        rows.append({
            "Candidate": p.get("candidate_name") or f,
            "Title": p.get("job_title") or "-",
            "Years (est.)": p.get("years_experience"),
            "Education": p.get("education") or "-",
            "Languages": ", ".join(p.get("languages") or []) or "-",
            "Skills": ", ".join(p.get("skills") or []) or "-",
            "Unique skills": ", ".join(unique[f]) or "-",
        })
    return {"rows": rows, "common": sorted(common)}


def experience_summaries(files: list[str], profiles: list[dict], language: str = "English") -> dict[str, str]:
    """Optional AI step: short experience summary per candidate, grounded in each CV's own excerpts."""
    by_file = {p["file_name"]: p for p in profiles}
    blocks = []
    for f in files:
        if f not in by_file:
            continue
        hits = search("work experience employment projects responsibilities", top=3, file_name=f)
        text = "\n".join(h["content"][:700] for h in hits) or "(no excerpts)"
        blocks.append(f"### {f}\n{text}")

    resp = _client.chat.completions.create(
        model=settings.chat_deployment,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": f"Language: {language}\n\n" + "\n\n".join(blocks)},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content).get("summaries") or {}
    return {f: str(data.get(f, "")) for f in files if f in by_file}