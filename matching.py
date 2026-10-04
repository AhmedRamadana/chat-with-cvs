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

MAX_JD_CHARS = 4000     # protection against huge pasted job descriptions
EXCERPTS = 8            # supporting CV excerpts sent to the scoring step
EXCERPT_CHARS = 600

REQ_PROMPT = """Extract the requirements of this job description. Return ONLY JSON:
{
  "job_title": "",
  "must_have_skills": [],
  "nice_to_have_skills": [],
  "min_years": null,
  "languages": [],
  "search_query": ""
}
Rules: skills are short names in English lowercase (e.g. "python", "sql"). Use [] or null when not stated.
Never invent requirements. search_query = under 15 English keywords that best describe the role."""

SCORE_PROMPT = """You rank candidates for a job. You get the job requirements, ALL candidate profiles,
and some CV excerpts. Return ONLY JSON:
{"candidates": [{"file_name": "", "score": 0, "matched_skills": [], "missing_skills": [], "reason": ""}]}

Rules:
- Include EVERY candidate from the profiles, using the exact file_name.
- score is an integer 0-100. Weights: must-have skills coverage (about 50%), relevant experience and job title
  (about 30%), years of experience vs min_years (about 10%), nice-to-have skills and languages (about 10%).
- A candidate with none of the must-have skills and an unrelated title must score below 20.
- Use ONLY the provided data. Never infer a skill that is not written. years_experience is an estimate.
- matched_skills / missing_skills refer to the job's must-have skills.
- reason: 1-2 short sentences explaining the score, in the same language as the job description."""


def _json_call(system: str, user: str) -> dict:
    resp = _client.chat.completions.create(
        model=settings.chat_deployment,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


def _profile_line(p: dict) -> str:
    return (
        f"- File: {p['file_name']} | Name: {p.get('candidate_name') or 'unknown'} "
        f"| Title: {p.get('job_title') or 'unknown'} "
        f"| Years (estimate): {p.get('years_experience') if p.get('years_experience') is not None else 'unknown'} "
        f"| Skills: {', '.join((p.get('skills') or [])[:25]) or 'none listed'} "
        f"| Languages: {', '.join(p.get('languages') or []) or 'none listed'} "
        f"| Education: {p.get('education') or 'unknown'}"
    )


def match_job(job_description: str, profiles: list[dict]) -> dict:
    """Returns {"requirements": {...}, "ranking": [ {file_name, name, title, score, matched, missing, reason}, ... ]}"""
    jd = job_description.strip()[:MAX_JD_CHARS]
    if not jd:
        raise ValueError("Job description is empty")
    if not profiles:
        raise ValueError("No CVs are indexed yet")

    # Step 1: understand the job (cheap call)
    req = _json_call(REQ_PROMPT, jd)
    query = str(req.get("search_query") or jd[:200])[:300]

    # Step 2: supporting excerpts (hybrid search with a SHORT query, never the whole job text)
    hits = search(query, top=EXCERPTS)
    excerpts = "\n\n---\n\n".join(h["content"][:EXCERPT_CHARS] for h in hits) or "(none)"

    user_msg = (
        f"JOB REQUIREMENTS:\n{json.dumps(req, ensure_ascii=False)}\n\n"
        f"JOB DESCRIPTION (original language reference):\n{jd[:1500]}\n\n"
        f"CANDIDATE PROFILES (ALL {len(profiles)}):\n" + "\n".join(_profile_line(p) for p in profiles) +
        f"\n\nCV EXCERPTS:\n{excerpts}"
    )
    raw = _json_call(SCORE_PROMPT, user_msg)

    # Validate: never trust model output blindly. Every real candidate must appear exactly once.
    by_file = {p["file_name"]: p for p in profiles}
    scored = {}
    for c in raw.get("candidates") or []:
        f = c.get("file_name")
        if f in by_file and f not in scored:
            try:
                score = max(0, min(100, int(c.get("score", 0))))
            except (TypeError, ValueError):
                score = 0
            scored[f] = {
                "score": score,
                "matched": [str(s) for s in (c.get("matched_skills") or [])],
                "missing": [str(s) for s in (c.get("missing_skills") or [])],
                "reason": str(c.get("reason") or ""),
            }

    ranking = []
    for f, p in by_file.items():
        s = scored.get(f, {"score": 0, "matched": [], "missing": [], "reason": "Not scored by the model."})
        ranking.append({"file_name": f, "name": p.get("candidate_name") or "", "title": p.get("job_title") or "", **s})
    ranking.sort(key=lambda r: r["score"], reverse=True)
    return {"requirements": req, "ranking": ranking}