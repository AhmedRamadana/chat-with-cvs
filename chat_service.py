from openai import AzureOpenAI

from config import settings
from lang_utils import MESSAGES, OR_WORD, FALLBACK_EXAMPLE, REPLY_INSTRUCTION, reply_language
from query_planner import plan
from search_service import get_indexed_cvs, search

_client = AzureOpenAI(
    azure_endpoint=settings.openai_endpoint,
    api_key=settings.openai_key,
    api_version=settings.openai_api_version,
    timeout=60,
    max_retries=4,
)

MAX_QUESTION_CHARS = 3000   # protection against huge pasted texts
MAX_CHUNKS = 16             # cap on excerpts sent to the model
TOP_SPECIFIC = 4            # chunks per targeted candidate
TOP_GENERAL = 5             # chunks for an unfiltered search

# Marker the model adds when nothing in the CVs supports its answer
NO_EVIDENCE = "[[NO_EVIDENCE]]"

# Backup check: phrases that mean "not found" in case the model forgets the marker
NOT_FOUND_PHRASES = [
    # Arabic
    "لا يوجد", "لا توجد", "لم أجد", "لم اجد", "غير مذكور", "لا يذكر", "لا تذكر", "مفيش",
    # English
    "could not find", "not found", "no cv", "not mentioned", "not stated", "no information",
]

# Vague "who is the best?" questions (normalized: lowercase, no punctuation).
# With no earlier context these cannot be answered without a role or criteria.
VAGUE_BEST = {
    "مين الأحسن", "مين الافضل", "مين الأفضل", "مين احسن واحد", "مين أحسن واحد",
    "مين افضل واحد", "مين أفضل واحد", "مين احسن مرشح", "مين أحسن مرشح",
    "مين افضل مرشح", "مين أفضل مرشح",
    "who is the best", "who is best", "who is the best candidate",
    "who is the top candidate", "best candidate", "top candidate",
    # Franco-Arabic
    "meen el a7san", "meen a7san", "meen a7san wa7ed", "meen a7san morasha7", "meen el afdal",
    "meen afdal", "meen afdal wa7ed", "meen afdal morasha7", "meen el ahsan", "meen ahsan",
}

SYSTEM_PROMPT = """You are an HR assistant that answers questions about a set of uploaded CVs.
You get two kinds of context:
  1) CANDIDATE PROFILES: structured data (name, title, years, skills, languages, education, email, phone).
     If the header says ALL candidates, it is the complete list.
  2) CV EXCERPTS: raw text, each starting with [CV: file name]. Use them for details.

GROUNDING RULES (strict):
- Use ONLY the provided context. Never use outside knowledge about the candidates, companies or schools.
- Do not infer facts that are not written. Example: do not say someone knows Docker because they know Kubernetes.
  If something is only implied, say it is "not explicitly stated".
- If the answer is not in the context, say clearly that you could not find it in the uploaded CVs. Do not guess,
  and do not fill the gap with generic advice.
- If the question is about a person who is not in the profiles, answer with one short sentence saying that
  no CV was uploaded for that person (use the name as the user wrote it). Do not add anything else about them,
  even if you know who they are from outside knowledge.
- If two CVs give conflicting information, report both versions and name each file.
- years_experience is an automatic estimate: when you use it, say it is approximate.
- If a question has nothing to do with the CVs (general knowledge, chit-chat), politely say you can only
  answer questions about the uploaded CVs.

CITATION RULES:
- After every fact, put the source in square brackets using the exact file name, e.g. [resume Software.pdf].
- For "all candidates" questions, cover EVERY candidate in the profiles; if a field is missing for someone,
  say it is not stated in their CV instead of skipping them.
- If NOTHING in the context supports your answer (the person or fact is not in the CVs), put the exact marker
  [[NO_EVIDENCE]] on its own at the very end of your reply, and cite no files.

STYLE:
- You may receive several numbered questions. Answer each one separately, in order, under a short number.
- If you rely on an assumption (e.g. no role was given), state it in one short line.
- Use the conversation history to understand follow-ups.
- The user message ends with a REPLY LANGUAGE line. Follow it exactly, whatever language the history or the CVs use."""


# ---------------------------------------------------------------- helpers
def _profile_line(p: dict) -> str:
    """One profile as a single text line for the model."""
    years = p.get("years_experience")
    return (
        f"- File: {p['file_name']} | Name: {p.get('candidate_name') or 'unknown'} "
        f"| Title: {p.get('job_title') or 'unknown'} "
        f"| Years (estimate): {years if years is not None else 'unknown'} "
        f"| Skills: {', '.join((p.get('skills') or [])[:20]) or 'none listed'} "
        f"| Languages: {', '.join(p.get('languages') or []) or 'none listed'} "
        f"| Education: {p.get('education') or 'unknown'} "
        f"| Email: {p.get('email') or 'unknown'} | Phone: {p.get('phone') or 'unknown'}"
    )


def _cited_files(text: str, profiles: list[dict]) -> set[str]:
    """Files the answer actually mentions, by file name or by candidate name."""
    low = text.lower()
    cited = set()
    for p in profiles:
        name = (p.get("candidate_name") or "").strip().lower()
        if p["file_name"].lower() in low or (len(name) > 3 and name in low):
            cited.add(p["file_name"])
    return cited


def _clean_history(history: list[dict]) -> list[dict]:
    """Send only role/content to the model. The UI stores extra keys (sources, evidence)."""
    return [{"role": m["role"], "content": m["content"]} for m in history[-6:]]


def _looks_like_not_found(text: str) -> bool:
    """Backup check: the answer says 'not found' even if the model forgot the marker."""
    low = text.lower()
    return any(p in low for p in NOT_FOUND_PHRASES)


def _normalize(text: str) -> str:
    for ch in "?؟!.,،":
        text = text.replace(ch, " ")
    return " ".join(text.lower().split())


def _clarify_best(profiles: list[dict], lang: str) -> str:
    """Ask for a role/criteria, offering real options taken from the indexed job titles, in the user's language."""
    titles = []
    for p in profiles:
        t = (p.get("job_title") or "").strip()
        if t and t not in titles:
            titles.append(t)
    opts = titles[:3]
    if opts:
        examples = (", ".join(opts[:-1]) + OR_WORD[lang] + opts[-1]) if len(opts) > 1 else opts[0]
    else:
        examples = FALLBACK_EXAMPLE[lang]
    return MESSAGES["clarify_best"][lang].format(examples=examples)


# ---------------------------------------------------------------- main entry
def answer(question, history=None, profiles=None):
    """Returns (answer_text, sources, evidence).
    sources  = CV files the answer actually cites (empty when nothing supports the answer).
    evidence = {"profiles": [...], "excerpts": [...]} so the UI can show what the answer is based on."""
    question = question.strip()[:MAX_QUESTION_CHARS]
    history = history or []
    profiles = profiles if profiles is not None else get_indexed_cvs()
    by_file = {p["file_name"]: p for p in profiles}
    empty_evidence = {"profiles": [], "excerpts": []}

    lang = reply_language(question, history)   # "ar" | "en" | "mixed" (Franco -> "en"): decided in code, not guessed by the model

    if not profiles:
        return MESSAGES["no_index"][lang], [], empty_evidence

    # ---- Step 0: vague "who is the best?" with no earlier context -> ask, don't guess ----
    # Done in code (not in the prompt) because the model does not follow this rule reliably.
    if not history and _normalize(question) in VAGUE_BEST:
        return _clarify_best(profiles, lang), [], empty_evidence

    # ---- Step 1: Planner (split, resolve context, classify, clarify or refuse) ----
    p = plan(question, history, profiles)

    if p["action"] == "refuse":
        return MESSAGES["out_of_scope"][lang], [], empty_evidence

    if p["action"] == "clarify":
        return p["clarifying_question"], [], empty_evidence

    items = p["items"]
    needs_all = any(it["scope"] == "all" for it in items)

    # ---- Step 2: Retrieve excerpts for EVERY item (mixed messages work naturally) ----
    seen, hits = set(), []

    def add(rows):
        for h in rows:
            key = (h["file_name"], h["chunk_index"])
            if key not in seen:
                seen.add(key)
                hits.append(h)

    for it in items:
        if it["scope"] == "specific":
            # Targeted: search INSIDE each named candidate's file, so the right CV is never missed
            for f in it["target_files"]:
                add(search(it["search_query"], top=TOP_SPECIFIC, file_name=f))
        else:
            add(search(it["search_query"], top=TOP_GENERAL))
    hits = hits[:MAX_CHUNKS]

    # ---- Step 3: Choose which profiles to show the model ----
    if needs_all:
        shown = profiles                                   # complete list: nobody gets skipped
        header = f"CANDIDATE PROFILES (ALL {len(profiles)} candidates):"
    else:
        wanted = {h["file_name"] for h in hits}
        for it in items:
            wanted.update(it["target_files"])
        shown = [by_file[f] for f in wanted if f in by_file]
        header = "CANDIDATE PROFILES (only the candidates relevant to this question):"

    profile_block = header + "\n" + "\n".join(_profile_line(x) for x in shown)
    excerpts = "\n\n---\n\n".join(h["content"] for h in hits) or "(no excerpts found)"
    numbered = "\n".join(f"{i + 1}. {it['question']}" for i, it in enumerate(items))

    # ---- Step 4: Generate the answer (low temperature = less guessing) ----
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += _clean_history(history)
    messages.append({
        "role": "user",
        "content": f"{profile_block}\n\nCV EXCERPTS:\n{excerpts}\n\nQuestions to answer (in order):\n{numbered}"
                   f"\n\nREPLY LANGUAGE: {REPLY_INSTRUCTION[lang]}",
    })
    resp = _client.chat.completions.create(
        model=settings.chat_deployment, messages=messages, temperature=0.1
    )
    text = resp.choices[0].message.content

    # ---- Step 5: Citations ----
    no_evidence = NO_EVIDENCE in text
    text = text.replace(NO_EVIDENCE, "").strip()

    # Backup: model forgot the marker, but the answer is clearly "not found" and names no CV/candidate
    if not no_evidence and not _cited_files(text, profiles) and _looks_like_not_found(text):
        no_evidence = True

    if no_evidence:
        return text, [], empty_evidence                    # nothing supports it: no sources, no evidence

    cited = _cited_files(text, profiles)
    if not cited:                                          # model named no one: fall back to what was retrieved
        cited = {h["file_name"] for h in hits}
    sources = sorted(cited)

    evidence = {
        "profiles": [x for x in shown if needs_all or x["file_name"] in cited],
        "excerpts": sorted(
            [{"file_name": h["file_name"], "chunk_index": h["chunk_index"], "content": h["content"]}
             for h in hits],
            key=lambda e: (e["file_name"] not in cited, e["file_name"], e["chunk_index"]),
        ),
    }
    return text, sources, evidence