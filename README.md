# Chat with CVs

A Streamlit app to **upload at least 8 CVs (PDF), index them, and chat with them**.
Every answer is grounded in the CV text and shows its sources and evidence.

**Azure services:** Blob Storage (original files) · Azure AI Search (hybrid keyword + vector index) · Azure OpenAI (chat + embeddings).

---

## 1. Project structure

```
chat-with-cvs/
│
├── app.py                  UI (Streamlit): upload, index, tools, chat
│
├── ── Chat pipeline ───────────────────────────────────────────────
├── chat_service.py         answer(): the main entry point of the chat
├── query_planner.py        Planner: split, resolve context, route, clarify/refuse
├── search_service.py       Azure AI Search: schema, upload, delete, hybrid search
│
├── ── Indexing pipeline ───────────────────────────────────────────
├── indexer.py              index_pending(): incremental indexing + duplicates + rejects
├── ingestion.py            validate, extract text, chunk, GPT profile, embeddings
├── blob_service.py         Azure Blob: upload / list / download / rejected metadata
│
├── ── Extra features ──────────────────────────────────────────────
├── matching.py             Job Matching (rank all candidates for a job description)
├── compare.py              Comparison table + optional AI experience summary
│
├── ── Shared ──────────────────────────────────────────────────────
├── config.py               Reads .env, stops early if a variable is missing
├── errors.py               friendly(e): readable errors, never leaks keys/CV data
│
├── ── Quality ─────────────────────────────────────────────────────
├── eval_cases.py           28 test cases (question + automatic checks)
├── run_eval.py             Runs the cases and prints a pass rate per group
├── security_check.py       10 security / failure-simulation checks
├── test_connections.py     Quick check that the 3 Azure services respond
│
├── requirements.txt        Python dependencies
├── .env.example            Template for secrets (copy to .env, never commit .env)
├── .gitignore              Ignores .env, .venv, eval_results.json, sample_cvs/
├── README.md               This file
└── DEMO.md                 Presentation script (5-7 minutes)
```

### What each module is responsible for

| Module | Main functions | Responsibility |
|---|---|---|
| `app.py` | `show_report`, `render_evidence`, `build_suggestions` | Screens only. No business logic. |
| `chat_service.py` | `answer(question, history, profiles)` | Orchestrates one chat turn and returns `(text, sources, evidence)` |
| `query_planner.py` | `plan(...)` | Asks GPT to split the message, classify each part, and choose search / clarify / refuse. Validates GPT's output |
| `search_service.py` | `ensure_index`, `recreate_index`, `upload_documents`, `delete_cv`, `get_indexed_cvs`, `get_chunk_counts`, `filter_profiles`, `search` | Everything that talks to Azure AI Search. Contains `_guard()` |
| `indexer.py` | `index_pending(...)` | Decides per file: skip, duplicate, reject, add, or update |
| `ingestion.py` | `validate_pdf`, `content_hash`, `extract_text`, `chunk_text`, `extract_profile`, `looks_like_cv`, `analyze_cv`, `build_documents` | Turns a PDF into index-ready documents. `analyze_cv` is cheap, `build_documents` is the expensive one (embeddings) |
| `blob_service.py` | `upload_cv`, `list_cvs`, `download_cv`, `list_rejected`, `mark_rejected`, `clear_rejected`, `delete_cv_blob` | Everything that talks to Blob Storage |
| `matching.py` | `match_job(...)` | Extracts job requirements, then scores **every** candidate |
| `compare.py` | `compare_table`, `experience_summaries` | Deterministic comparison table (no GPT) + optional summary |

---

## 2. Architecture

### 2.1 Overview

```
                        ┌──────────────────────────────┐
                        │        Streamlit (app.py)    │
                        └───────┬──────────────┬───────┘
                 upload / index │              │ chat / tools
                                ▼              ▼
                       ┌──────────────┐   ┌───────────────┐
                       │  indexer.py  │   │chat_service.py│
                       └──┬────────┬──┘   └──┬─────────┬──┘
                          │        │         │         │
              ┌───────────▼─┐  ┌───▼──────┐  │   ┌─────▼────────┐
              │ blob_service│  │ingestion │  │   │query_planner │
              └──────┬──────┘  └───┬──────┘  │   └─────┬────────┘
                     │             │         │         │
                     ▼             ▼         ▼         ▼
              ┌────────────┐ ┌─────────────────────────────────┐
              │ Azure Blob │ │  search_service.py → AI Search  │
              │ (originals)│ │  ahmed-cvs-index (chunks+vectors)│
              └────────────┘ └─────────────────────────────────┘
                                     ▲
                       Azure OpenAI (embeddings + GPT) is called by
                       ingestion, query_planner, chat_service, matching, compare
```

### 2.2 Indexing flow (what "Index new / changed CVs" does)

```
Blob file
  │
  ├─ same name + same hash as indexed? ───────────► SKIPPED   (no Azure call)
  ├─ rejected before with the same hash? ─────────► SKIPPED   (no GPT call)
  ├─ hash equals another file's hash? ────────────► DUPLICATE (identical file)
  │
  └─ analyze_cv  (extract text + GPT profile + is_cv)   ← cheap
        │
        ├─ not a CV ──────────────────────────────► REJECTED  (saved in Blob metadata)
        ├─ same email + name + job title as another CV ► DUPLICATE (same person)
        └─ build_documents  (chunks + embeddings)   ← expensive, only reached here
              └─► upload to AI Search ──────────────► ADDED / UPDATED
```

Decisions go from **cheapest to most expensive**, so unchanged or invalid files cost nothing.

### 2.3 Chat flow (what happens for one question)

```
Question + history
   │
   ├─ vague "who is the best?" and no history? ──► ask for role/criteria (done in code)
   │
   ▼
Planner (GPT, JSON)
   │
   ├─ refuse   ──► fixed polite reply, no sources
   ├─ clarify  ──► one clarifying question, no search
   └─ search   ──► items[], each with scope:
        │
        ├─ "all"      → ALL candidate profiles + a hybrid search
        └─ "specific" → hybrid search INSIDE that candidate's CV + their profile
                │
                ▼
        GPT answers with strict rules (only provided context, cite file names)
                │
                ▼
        Sources = files the answer really cites
        Evidence = chunks + profiles shown in the UI
        (nothing supports the answer → no sources, no evidence)
```

### 2.4 What is stored in the index

One **chunk** = ~1000 characters of a CV (150 overlap), prefixed with `[CV: file name]`.
Every chunk carries the candidate's profile fields, and **chunk 0 of each CV is that CV's profile row**
(`chunk_index eq 0` returns exactly one row per CV, so "all candidates" never misses anyone).

| Field | Purpose |
|---|---|
| `id` | MD5 of file name + chunk number (re-indexing replaces instead of duplicating) |
| `content`, `content_vector` | Chunk text + 1536-dim embedding (hybrid search) |
| `file_name`, `chunk_index` | Source + position (also used to search inside one CV) |
| `content_hash` | SHA-256 of the file: detects identical files and changed files |
| `candidate_name`, `email`, `phone`, `job_title`, `years_experience`, `skills`, `languages`, `education` | Structured profile extracted by GPT |

---

## 3. Azure resources (shared with the team)

| Service | Name | Note |
|---|---|---|
| Resource group | `GBG-AI-3` | shared |
| Blob container | `ahmed-cvs` (private) | original PDFs + rejection metadata |
| AI Search | `cvs-chat` (Free) | **SHARED**: max 3 indexes, 50 MB. Ours: `ahmed-cvs-index` |
| Azure OpenAI | `Gbg-ai-g3` (East US) | chat: `gpt-4.1-mini-4`, embeddings: `text-embedding-3-small` (1536) |

**Do not touch `cv-index` or `cvs-index`** (teammates'). `_guard()` in `search_service.py` refuses any index other than `ahmed-cvs-index`. Never remove it.
If you get HTTP 429, change `AZURE_OPENAI_CHAT_DEPLOYMENT` in `.env` to another existing deployment.

---

## 4. Setup and run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # fill in YOUR OWN keys from the Azure portal
python test_connections.py    # expect 4 green checks
streamlit run app.py          # first run: Rebuild index once, afterwards "Index new / changed CVs"
```

Never share keys in chat or screenshots. If a key leaks, regenerate it in the portal.

## 5. Tests

```powershell
python run_eval.py            # 28 cases (or: python run_eval.py H1 Q4)
python security_check.py      # 10 checks
```

Last results: **eval 28/28** (avg 5.8 s per answer), **security 10/10**.

| Group | Cases |
|---|---|
| Search | 7 (skills, email, education, keyword, person lookup) |
| Coverage | 5 (all candidates, comparisons) |
| Understanding | 5 (multi-question, long text, typo, vague, mixed languages) |
| Context | 3 (follow-ups, topic change) |
| Hallucination | 6 (not in CV, unknown person, off-topic, forced guess) |
| Language | 2 (Arabic / English) |

Notes: the model is not deterministic, so run the eval more than once; a case that flips is a fragile case.
`eval_cases.py` expectations are written for this project's CVs (update the names if you change CVs).
H5/H6 were relaxed after manual review of the answers. `eval_results.json` contains CV data: do not share it.

## 6. Where to change things

| Want to change | File |
|---|---|
| Chunk size | `ingestion.py` (`CHUNK_SIZE`, `CHUNK_OVERLAP`), then Rebuild |
| Index fields | `search_service.py` (`_build_index`), then Rebuild |
| Profile extraction / "is this a CV?" | `ingestion.py` (`PROFILE_PROMPT`, `CV_KEYWORDS`) |
| Duplicate rules | `indexer.py` (`_candidate_key`) |
| Question understanding and routing | `query_planner.py` (`PLANNER_PROMPT`) |
| Answer strictness, citations, vague-question list | `chat_service.py` (`SYSTEM_PROMPT`, `VAGUE_BEST`) |
| Job matching weights | `matching.py` (`SCORE_PROMPT`) |
| Test cases | `eval_cases.py` |

Rebuild is needed only when the schema or chunking changes. Prompt and UI edits do not need it.

## 7. Key design decisions

- **Duplicate = same email AND name AND job title.** Canva templates share a placeholder email, so email alone wrongly dropped CVs. An empty field means "not enough evidence", so the CV is indexed.
- **Non-CV files are rejected, remembered in Blob metadata (with the hash), and never auto-deleted.** Deleting is a button with a confirmation.
- **Structured profiles instead of search only.** Questions like "job title of everyone" or "how many have 5+ years" need all the data; a top-k search misses CVs.
- **"Who is the best?" with no context is handled in code, not in the prompt**, because the model did not follow that rule reliably.
- **Planner output is validated.** Unknown file names are dropped, and a "specific" item with no identified person becomes "all".
- **Cost order:** hash check (free) → GPT profile (cheap) → embeddings (most expensive, only for files that will really be indexed).

## 8. Known limits

- `years_experience` and Match % are AI estimates.
- Streamlit cannot truly disable a button while a run is in progress.
- Indexing 20 CVs was inferred (only 10-11 CVs were tested): cost is roughly linear and the hash cache makes re-runs free.
- Real Azure outages were simulated with wrong settings, because the resources are shared.
- `build_suggestions` in `app.py` (suggested questions generated from the profiles) was added last and is not covered by the eval.
- CVs contain real personal data: do not share outputs outside the team.