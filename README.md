# Chat with CVs

A Streamlit app to **upload at least 8 CVs (PDF), index them, and chat with them**.
Every answer is grounded in the CV text and shows its sources and evidence.

**Azure services:** Blob Storage (original files) · Azure AI Search (hybrid keyword + vector index) · Azure OpenAI (chat + embeddings).

## Contents

1. [Features](#1-features) · 2. [Project structure](#2-project-structure) · 3. [Architecture](#3-architecture) ·
4. [Language behavior](#4-language-behavior) · 5. [Azure resources](#5-azure-resources-shared-with-the-team) ·
6. [Setup and run](#6-setup-and-run) · 7. [How to use the app](#7-how-to-use-the-app) · 8. [Tests](#8-tests) ·
9. [Where to change things](#9-where-to-change-things) · 10. [Key design decisions](#10-key-design-decisions) ·
11. [Known limits](#11-known-limits) · 12. [Troubleshooting](#12-troubleshooting) · 13. [What was built, phase by phase](#13-what-was-built-phase-by-phase)

---

## 1. Features

| Area | What it does |
|---|---|
| **Upload** | PDF only, not empty, under 10 MB, must start with `%PDF`; file names are sanitized (spaces, `—`, Arabic names are fine); each failed file is reported on its own |
| **Incremental indexing** | Only new or changed files are processed. A SHA-256 hash makes re-runs free (`skipped`) |
| **Duplicates** | Same file under another name (hash), or same person (email AND name AND job title) |
| **Not-a-CV detection** | Files like `Use Cases.pdf` are rejected, remembered in Blob metadata, and never auto-deleted |
| **Structured profiles** | GPT extracts name, email, phone, job title, years, skills, languages, education for every CV |
| **Chat** | Splits several questions in one message, resolves follow-ups ("وايه ايميله؟"), asks for clarification when needed, refuses off-topic questions |
| **Citations** | `Sources` = files the answer really cites, plus an **Evidence** panel with the exact chunks and profiles |
| **Anti-hallucination** | Strict prompt, `[[NO_EVIDENCE]]` marker, backup "not found" check, and an automatic eval that measures it |
| **Languages** | Arabic → Arabic, English → English, mixed Arabic/English → mixed, Franco-Arabic → English |
| **Job Matching** | Paste a job description; every candidate is scored and ranked with matched/missing skills and a reason |
| **Compare** | Side-by-side table from structured data (no GPT) + optional AI experience summary |
| **Candidates table** | Filters (skill, min years, title, language) and a Chunks column showing indexing status |
| **Safety** | `_guard()` refuses any index other than `ahmed-cvs-index`; readable errors that never leak keys or CV text |

---

## 2. Project structure

```
chat-with-cvs/
│
├── app.py                  UI (Streamlit): upload, index, tools, chat
│
├── ── Chat pipeline ───────────────────────────────────────────────
├── chat_service.py         answer(): the main entry point of the chat
├── query_planner.py        Planner: split, resolve context, route, clarify/refuse
├── search_service.py       Azure AI Search: schema, upload, delete, hybrid search
├── lang_utils.py           Language detection (ar / en / mixed / franco) + fixed replies
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
├── eval_cases.py           35 test cases (question + automatic checks)
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
| `app.py` | `load_profiles`, `show_report`, `render_evidence`, `build_suggestions`, `label_of` | Screens only. No business logic |
| `chat_service.py` | `answer(question, history, profiles)` | Orchestrates one chat turn, returns `(text, sources, evidence)`. Helpers: `_profile_line`, `_cited_files`, `_clean_history`, `_looks_like_not_found`, `_normalize`, `_clarify_best` |
| `query_planner.py` | `plan(...)` | Asks GPT to split the message, classify each part, and choose `search` / `clarify` / `refuse`. Validates GPT's output |
| `search_service.py` | `ensure_index`, `recreate_index`, `upload_documents`, `delete_cv`, `get_indexed_cvs`, `get_chunk_counts`, `filter_profiles`, `search` | Everything that talks to Azure AI Search. Contains `_guard()` |
| `lang_utils.py` | `detect_language`, `reply_language`, `is_mixed`, `is_franco`, `has_arabic`, `MESSAGES`, `REPLY_INSTRUCTION` | Decides the reply language **in code**; fixed replies per language. No Azure imports, so it is testable offline |
| `indexer.py` | `index_pending(...)`, `_candidate_key`, `_norm` | Decides per file: skip, duplicate, reject, add, or update |
| `ingestion.py` | `validate_pdf`, `safe_blob_name`, `content_hash`, `extract_text`, `chunk_text`, `extract_profile`, `looks_like_cv`, `analyze_cv`, `build_documents`, `embed_texts` | Turns a PDF into index-ready documents. `analyze_cv` is cheap, `build_documents` is the expensive one (embeddings) |
| `blob_service.py` | `upload_cv`, `list_cvs`, `download_cv`, `list_rejected`, `mark_rejected`, `clear_rejected`, `delete_cv_blob` | Everything that talks to Blob Storage |
| `matching.py` | `match_job(...)` | Extracts job requirements, then scores **every** candidate and validates the output |
| `compare.py` | `compare_table`, `experience_summaries` | Deterministic comparison table (no GPT) + optional summary |
| `config.py` / `errors.py` | `settings`, `friendly(e)` | Settings and readable error messages |

---

## 3. Architecture

### 3.1 Overview

```
                        ┌──────────────────────────────┐
                        │        Streamlit (app.py)    │
                        └───────┬──────────────┬───────┘
                 upload / index │              │ chat / tools
                                ▼              ▼
                       ┌──────────────┐   ┌───────────────┐
                       │  indexer.py  │   │chat_service.py│──► lang_utils.py
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

### 3.2 Indexing flow (what "Index new / changed CVs" does)

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
A failure on one file is recorded in the report and does not stop the others.

### 3.3 Chat flow (what happens for one question)

```
Question + history
   │
   ├─ language = reply_language(question, history)     (code, not the model)
   ├─ no CVs indexed? ────────────────────────────► fixed message in that language
   ├─ vague "who is the best?" and no history? ───► ask for role/criteria (done in code)
   │
   ▼
Planner (GPT, JSON)
   │
   ├─ refuse   ──► fixed polite reply in the user's language, no sources
   ├─ clarify  ──► one clarifying question, no search
   └─ search   ──► items[], each with scope:
        │
        ├─ "all"      → ALL candidate profiles + a hybrid search
        └─ "specific" → hybrid search INSIDE that candidate's CV + their profile
                │
                ▼
        GPT answers with strict rules + a final "REPLY LANGUAGE" line
                │
                ▼
        Sources = files the answer really cites
        Evidence = chunks + profiles shown in the UI
        (nothing supports the answer → no sources, no evidence)
```

| Planner decision | Meaning | Example |
|---|---|---|
| `refuse` | Off-topic: fixed reply, no sources | "ايه عاصمة فرنسا؟", "tell me a joke" |
| `clarify` | Cannot answer without more info: ask, don't guess | "مين الأحسن؟" (no context) |
| `search / all` | About everyone: send all profiles so nobody is missed | "المسمى الوظيفي لكل واحد" |
| `search / specific` | About one person: search inside that CV only | "ايه تعليم أحمد؟" |

### 3.4 What is stored in the index

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

## 4. Language behavior

The reply language is decided **in code** (`lang_utils.py`) and sent to the model as a final `REPLY LANGUAGE` line,
because the model cannot reliably tell Franco-Arabic from English on its own.

| The user writes | Example | The app replies |
|---|---|---|
| Arabic | `مين عنده خبرة في Python؟` | Arabic |
| English | `Who knows Docker?` | English |
| Mixed Arabic + English | `مين عنده experience في Deep Learning؟` | Mixed (same code-switching style) |
| Franco-Arabic (Arabic in Latin letters) | `meen 3ando khebra fel Python?` | **English** |

How the input is classified:

- **Arabic letters present** → Arabic, or **mixed** if there are also **two or more English words** (3+ letters).
  A single English term (`Python`) keeps the message plain Arabic.
- **No Arabic letters** → **Franco** if a word mixes Latin letters with the digits 2, 3, 5, 6, 7, 8, 9
  (`3ando`, `7aga`, `ba3d`), or contains a strong Franco word (`meen`, `ezay`, `khebra`...), or two weak ones (`el`, `eh`...).
  Otherwise English.
- Tech tokens such as `Python3`, `k8s`, `3D`, `5years`, `S3` are treated as English.
- Very short unclear messages (1-2 Latin words, like `Ahmed`) reuse the language of the previous user message.
- Fixed replies (refusal, "no CVs indexed", clarifying question) exist in Arabic, English and mixed.
  File names, emails and technical terms are always kept as written.

---

## 5. Azure resources (shared with the team)

| Service | Name | Note |
|---|---|---|
| Resource group | `GBG-AI-3` | shared |
| Blob container | `ahmed-cvs` (private) | original PDFs + rejection metadata |
| AI Search | `cvs-chat` (Free) | **SHARED**: max 3 indexes, 50 MB. Ours: `ahmed-cvs-index` |
| Azure OpenAI | `Gbg-ai-g3` (East US) | chat: `gpt-4.1-mini-4`, embeddings: `text-embedding-3-small` (1536) |

**Do not touch `cv-index` or `cvs-index`** (teammates'). `_guard()` in `search_service.py` refuses any index other than
`ahmed-cvs-index`. Never remove it.
If you get HTTP 429, change `AZURE_OPENAI_CHAT_DEPLOYMENT` in `.env` to another existing deployment.

---

## 6. Setup and run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # fill in YOUR OWN keys from the Azure portal
python test_connections.py    # expect 4 green checks
streamlit run app.py
```

First run: open the sidebar → **Rebuild everything** → confirm → **Rebuild index** (once).
Afterwards use **Index new / changed CVs**.

`.env` variables (get the secrets from the portal, never share them in chat or screenshots):

| Variable | Where to find it |
|---|---|
| `AZURE_STORAGE_CONNECTION_STRING` | Storage account → Access keys |
| `AZURE_STORAGE_CONTAINER` | `ahmed-cvs` |
| `AZURE_SEARCH_ENDPOINT` / `AZURE_SEARCH_KEY` | `cvs-chat` → Overview / Keys (primary **admin** key) |
| `AZURE_SEARCH_INDEX` | `ahmed-cvs-index` (must stay exactly this name) |
| `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_KEY` | Foundry portal → Endpoints and keys |
| `AZURE_OPENAI_API_VERSION` | `2024-10-21` |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | `gpt-4.1-mini-4` (the **deployment** name, not the model name) |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | `text-embedding-3-small` |

If a key leaks, regenerate it in the portal and update `.env`.

---

## 7. How to use the app

1. **Upload CVs** (sidebar): choose PDFs → **Upload to Blob**. Warning shows if fewer than 8 are in storage.
2. **Index**: **Index new / changed CVs**. The report shows added / updated / skipped / duplicates / rejected / failed.
   - *Allow same candidate in two files* turns off the same-person duplicate check.
   - **Rejected files** panel: **Re-check** (if GPT was wrong) or delete from Blob (needs a confirmation checkbox).
   - **Rebuild index** is only needed when the schema or chunking changes.
3. **Tools** (expander):
   - **Candidates**: table with filters and a Chunks column.
   - **Job Matching**: paste a job description → **Rank candidates** → ranked list with match %, matched/missing skills, reason.
   - **Compare**: pick two or more candidates → table; optional **Add AI experience summary**.
4. **Chat**: ask in Arabic, English, or mixed (Franco is understood and answered in English). Open **Evidence** under any answer.
   **New chat** clears the conversation.

---

## 8. Tests

```powershell
python run_eval.py                       # all 35 cases
python run_eval.py H1 Q4 M1              # only some cases
python security_check.py                 # 10 checks
```

**Latest results**

| Check | Result |
|---|---|
| Eval, the 28 original cases | **28/28** (avg 5.8 s per answer) |
| Security | **10/10** |
| Language cases added later: L3-L7 (Franco → English) and M1-M2 (mixed) | **not run yet** (35 cases in total now) |

| Group | Cases | What it covers |
|---|---|---|
| Search | 7 | skills, email, education, exact keyword, person lookup |
| Coverage | 5 | all candidates, comparisons (must cite every CV) |
| Understanding | 5 | multi-question, long text, typo, vague question, mixed languages |
| Context | 3 | follow-ups, topic change |
| Hallucination | 6 | not in CV, unknown person, off-topic, forced guess |
| Language | 9 | Arabic, English, Franco → English (5), mixed (2) |

Check types in `eval_cases.py`: `all_of`, `none_of`, `sources` (`some`/`none`/`all`), `clarify`, `lang` (`ar`/`en`/`mixed`).

**Security checks:** `.env` is git-ignored · no key hard-coded in any `.py` · `friendly()` never echoes a secret ·
the container is private and anonymous download is refused (HTTP 409 also means "public access not permitted") ·
`_guard()` refuses `cv-index` and `cvs-index` (called directly, never via `recreate_index`, so no teammate index is ever at risk) ·
wrong deployment, empty index and wrong Search key give readable errors.

**How to read results**

- The model is not deterministic: run the eval more than once. A case that flips is a fragile case.
- Before changing code for a failed case, open `eval_results.json` and read the answer. Sometimes the answer is right and the expectation is wrong.
- `eval_cases.py` expectations are written for this project's CVs (Ahmed, Sebastian, Johnathan...). Update names if you change CVs.
- The `mixed` check is weak on purpose (Arabic + Latin words, which can also come from file names): read M1/M2 answers yourself.
- `eval_results.json` contains CV data: it is git-ignored, do not share it.

A manual checklist (upload, UI, Azure failures, security, performance) is in `Chat_with_CVs_Test_Guide.docx`.

---

## 9. Where to change things

| Want to change | File |
|---|---|
| Chunk size | `ingestion.py` (`CHUNK_SIZE`, `CHUNK_OVERLAP`), then Rebuild |
| Index fields | `search_service.py` (`_build_index`), then Rebuild |
| Profile extraction / "is this a CV?" | `ingestion.py` (`PROFILE_PROMPT`, `CV_KEYWORDS`) |
| Duplicate rules | `indexer.py` (`_candidate_key`) |
| Question understanding and routing | `query_planner.py` (`PLANNER_PROMPT`) |
| Answer strictness, citations, vague-question list | `chat_service.py` (`SYSTEM_PROMPT`, `VAGUE_BEST`) |
| Language rules, fixed replies, Franco words | `lang_utils.py` (`_STRONG`, `_WEAK`, `MESSAGES`, `REPLY_INSTRUCTION`) |
| Job matching weights | `matching.py` (`SCORE_PROMPT`) |
| Suggested questions | `app.py` (`build_suggestions`) |
| Test cases | `eval_cases.py` |

Rebuild is needed only when the schema or chunking changes. Prompt and UI edits do not need it.

---

## 10. Key design decisions

- **RAG, not fine-tuning:** cheaper, updatable without training, and gives sources.
- **Hybrid search:** vectors are weak on exact terms (Kubernetes, names); keywords cover that.
- **Structured profiles instead of search only:** "job title of everyone" or "how many have 5+ years" need all the data; top-k search misses CVs.
- **Duplicate = same email AND name AND job title.** Canva templates share a placeholder email, so email alone wrongly dropped CVs
  (only 6 of 11 were indexed). An empty field means "not enough evidence", so the CV is indexed.
- **Non-CV files are rejected, remembered in Blob metadata (with the hash), and never auto-deleted.**
- **Critical behavior lives in code, not in the prompt:** the model ignored the "who is the best?" rule, so it is a code check;
  the reply language is chosen by code and passed to the model explicitly.
- **Planner output is validated:** unknown file names are dropped, a "specific" item with no identified person becomes "all".
- **Cost order:** hash check (free) → GPT profile (cheap) → embeddings (most expensive, only for files that will really be indexed).
- **Comparison table without GPT:** built from structured data, so it cannot hallucinate.

---

## 11. Known limits

- `years_experience` and Match % are AI estimates.
- Language detection is a heuristic: a very short Franco sentence with no telltale word is treated as English (which is also the reply language, so the result is the same).
- Streamlit cannot truly disable a button while a run is in progress.
- Indexing 20 CVs was inferred (only 10-11 CVs were tested): cost is roughly linear and the hash cache makes re-runs free.
- Real Azure outages were simulated with wrong settings, because the resources are shared.
- `build_suggestions` and the language rules (Franco/mixed) were added last: the language logic was tested offline, but the model's actual replies in those cases have not been run through the eval yet.
- Free AI Search tier: 3 indexes and 50 MB, shared with teammates.
- CVs contain real personal data: do not share outputs outside the team.
- Deliberately postponed: PII masking (it conflicts with email questions), streaming, Semantic Ranker.

---

## 12. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Missing environment variable: ...` | `.env` is missing or incomplete: copy `.env.example` and fill it |
| `Azure OpenAI deployment not found` | `AZURE_OPENAI_CHAT_DEPLOYMENT` must be the deployment name from the Deployments page |
| `Azure OpenAI is busy (429)` | Shared deployment is busy: wait, or switch to another deployment in `.env` |
| `Azure credentials rejected` / HTTP 403 | Wrong key (use the **admin** key for Search) |
| `Safety check: refusing to touch an index...` | `AZURE_SEARCH_INDEX` is not `ahmed-cvs-index`: this is the protection working, fix `.env` |
| Candidates shows an error after a code change | Schema changed: sidebar → Rebuild index once |
| `too many values to unpack` in chat | `app.py` is an old version: `answer()` returns 3 values `(text, sources, evidence)` |
| A real CV was rejected as "not a CV" | Rejected files panel → **Re-check rejected files**, then Index again |
| Fewer CVs indexed than uploaded | Read the Index report: duplicates / rejected / failed are listed with the reason |
| PowerShell blocks `Activate.ps1` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

---

## 13. What was built, phase by phase

| Phase | What was added |
|---|---|
| **0 Foundation** | Azure resources (reused the shared Search and OpenAI instead of creating new ones: Standard Search would have cost about $249/month), `.env`, connection tests, text extraction check on all CVs |
| **1 Safe upload + incremental indexing** | Validation, SHA-256 hash, skip unchanged files, duplicate detection, readable errors, retries/timeouts on OpenAI calls |
| **2 Structured data** | GPT profile per CV stored as index fields, chunk 0 = profile row, filters, full coverage without `top=8` |
| **Dedup + not-a-CV fixes** | Same person = email AND name AND job title; `is_cv` + keywords; rejection stored in Blob metadata; delete only by button with confirmation |
| **3 Chat intelligence** | Planner (multi-question, context, clarify, refuse), `all`/`specific` routing, citations + Evidence, strict prompt, `[[NO_EVIDENCE]]`, backup not-found check |
| **4 Showcase features** | Job Matching, Compare, suggested questions, Chunks column |
| **5 Quality** | `eval_cases.py`, `run_eval.py`, `security_check.py`, manual checklist (Word guide) |
| **Fixes found by the eval** | "Who is the best?" moved to code; H5/H6 expectations relaxed after reading the answers; `.gitignore` and the HTTP 409 security check fixed |
| **Language rules** | `lang_utils.py`: Arabic → Arabic, English → English, mixed → mixed, Franco → English; fixed replies in 3 variants; 7 new eval cases |

Eval history: the first two runs scored 26/28; after fixing Q4 and relaxing H5/H6 (after manual review) it reached 28/28.