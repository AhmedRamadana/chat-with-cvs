import json

from openai import AzureOpenAI

from config import settings

_client = AzureOpenAI(
    azure_endpoint=settings.openai_endpoint,
    api_key=settings.openai_key,
    api_version=settings.openai_api_version,
    timeout=60,
    max_retries=4,
)

MAX_ITEMS = 5

PLANNER_PROMPT = """You prepare user messages for a CV question-answering system.
You receive: the CV roster (file | candidate name | job title), the recent conversation,
and the new user message. The user may write Arabic, English, or Franco-Arabic (Egyptian Arabic in Latin
letters with digits such as 3, 7, 5, 2, e.g. "meen 3ando python?"). Understand all three. Return ONLY a JSON object:
{
  "action": "search" | "clarify" | "refuse",
  "clarifying_question": "",
  "items": [
    {"question": "", "scope": "all" | "specific", "target_files": [], "search_query": ""}
  ]
}

Rules:
0. REFUSE: use action "refuse" (with items = []) ONLY when the message has nothing to do with the uploaded CVs
   or hiring: general knowledge ("capital of France"), jokes, chit-chat, coding help, math, news.
   A short reply like "yes" / "ok" to an earlier refusal is also "refuse" unless it clearly refers to a CV topic.
   NEVER refuse a question that asks for personal/professional data (email, phone, skills, experience,
   education, job title, languages) about a named person, EVEN IF that name belongs to a famous person
   or is not in the roster. Use "search" with scope "all" and target_files = [] in that case, so the system
   can answer that no CV was found for that person.
   Examples:
   - "what is the email of Mohamed Salah?" -> search (scope all). NOT refuse.
   - "ايه ايميل محمد صلاح؟" -> search (scope all). NOT refuse.
   - "who is Mohamed Salah?" -> refuse (general knowledge, not asking about CV data).
   - "what is the capital of France?" -> refuse.
1. SPLIT: break the message into separate items (max 5), keeping the user's order.
   A single simple question is one item.
2. SCOPE (decide per item, so a mixed message gets mixed scopes):
   - "all": concerns every/many candidates: list everyone, job title/experience of each, compare,
     rank, count, "who has X", "who is best for Y".
   - "specific": concerns one or a few identified candidates (by name, file, or a reference from the conversation).
3. TARGET FILES: for "specific" items, put the exact file names from the roster in target_files.
   Match by name, partial name, typo, or Arabic/English spelling (e.g. "احمد" = "Ahmed").
   Leave empty for "all" items, or if you cannot identify anyone.
4. CONTEXT: resolve pronouns and references ("he", "his email", "compare him with the other one")
   using the conversation. Every item.question must be fully standalone and include the candidate's name.
5. LONG MESSAGES: keep only the core ask in item.question. search_query must be short (under 15 words),
   in English, keyword-rich. Never paste long text into search_query.
6. CLARIFY: use action "clarify" ONLY when a useful answer is impossible, e.g.
   - a name matches more than one roster entry,
   - "best/top candidate" with no role or criteria and no earlier context,
   - a reference you cannot resolve from the conversation.
   Examples that MUST be "clarify" when the conversation has no earlier context:
   - "who is the best?" / "who is the top candidate?" / "مين الأحسن؟" / "مين الأفضل؟"
   Never assume a criterion (such as overall experience) yourself for these questions.
   If a reasonable assumption works for any other question, use "search" instead.
   Never ask about something the conversation already answered.
7. clarifying_question: ONE short question, offering 2-3 concrete options (real names or fields from the roster).
   Language: Arabic user -> Arabic, English user -> English, Franco-Arabic user -> English,
   mixed Arabic/English user -> the same Arabic-English mix.
8. item.question in the user's language (Franco-Arabic users: write it in English)."""


def _fallback(question: str) -> dict:
    # If the planner fails, behave safely: treat it as a whole-set question.
    return {
        "action": "search",
        "clarifying_question": "",
        "items": [{"question": question, "scope": "all", "target_files": [], "search_query": question[:300]}],
    }


def plan(question: str, history: list[dict], profiles: list[dict]) -> dict:
    roster = "\n".join(
        f"{p['file_name']} | {p.get('candidate_name') or '?'} | {p.get('job_title') or '?'}"
        for p in profiles
    ) or "(empty)"
    convo = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in (history or [])[-6:])
    user_msg = (
        f"CV roster:\n{roster}\n\n"
        f"Conversation so far:\n{convo or '(none)'}\n\n"
        f"New user message:\n{question}"
    )
    try:
        resp = _client.chat.completions.create(
            model=settings.chat_deployment,
            messages=[
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        p = json.loads(resp.choices[0].message.content)
    except Exception:
        return _fallback(question)

    # ---- Validate / clean the planner output (never trust it blindly) ----
    if p.get("action") == "refuse":
        return {"action": "refuse", "clarifying_question": "", "items": []}

    valid_files = {x["file_name"] for x in profiles}
    items = []
    for it in (p.get("items") or [])[:MAX_ITEMS]:
        q = str(it.get("question") or "").strip()
        if not q:
            continue
        scope = it.get("scope") if it.get("scope") in ("all", "specific") else "all"
        targets = [f for f in (it.get("target_files") or []) if f in valid_files]
        if scope == "specific" and not targets:
            scope = "all"  # could not identify the person: safest is to look at everyone
        items.append({
            "question": q,
            "scope": scope,
            "target_files": targets,
            "search_query": str(it.get("search_query") or q)[:300],
        })
    if not items:
        return _fallback(question)

    action = "clarify" if p.get("action") == "clarify" and p.get("clarifying_question") else "search"
    return {
        "action": action,
        "clarifying_question": str(p.get("clarifying_question") or ""),
        "items": items,
    }