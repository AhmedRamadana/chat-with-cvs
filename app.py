import streamlit as st

# ---------- Imports ----------
from blob_service import upload_cv, list_cvs, list_rejected, clear_rejected, delete_cv_blob
from chat_service import answer
from compare import compare_table, experience_summaries
from errors import friendly
from indexer import index_pending
from ingestion import safe_blob_name, validate_pdf
from matching import match_job
from search_service import (
    ensure_index, filter_profiles, get_chunk_counts, get_indexed_cvs, recreate_index,
)

st.set_page_config(page_title="Chat with CVs", page_icon="📄", layout="wide")
st.title("📄 Chat with CVs")


# ---------- Helper functions ----------
def load_profiles():
    """Read candidate profiles from the index. On failure, return an error
    message instead of crashing the app."""
    try:
        return get_indexed_cvs(), None
    except Exception as e:
        return [], friendly(e)


def show_report(rep):
    """Show the details of an indexing run. Used by both the Index and Rebuild buttons."""
    # Duplicates (same file content, or same email + name + job title)
    for m in rep["duplicates"]:
        st.warning(f"Duplicate skipped: {m}")
    # Analyzed and found not to be a CV (rejection is saved in Blob metadata)
    for m in rep["rejected"]:
        st.warning(f"Rejected (not a CV): {m}")
    # Rejected earlier with the same content (skipped without calling GPT)
    for m in rep["rejected_known"]:
        st.info(f"Previously rejected, skipped: {m}")
    # Failed (corrupted, no text, Azure error, ...)
    for m in rep["failed"]:
        st.error(m)


def render_evidence(sources, evidence):
    """Show sources + the exact excerpts the answer is based on."""
    if sources:
        st.caption("Sources: " + ", ".join(sources))
    if not evidence or not (evidence["profiles"] or evidence["excerpts"]):
        return
    with st.expander("🔎 Evidence (what this answer is based on)"):
        if evidence["profiles"]:
            st.markdown("**Candidate profiles used**")
            st.dataframe(
                [{
                    "File": p["file_name"],
                    "Name": p.get("candidate_name"),
                    "Title": p.get("job_title"),
                    "Years (est.)": p.get("years_experience"),
                    "Skills": ", ".join((p.get("skills") or [])[:12]),
                } for p in evidence["profiles"]],
                use_container_width=True,
            )
        for e in evidence["excerpts"]:
            st.markdown(f"**{e['file_name']}**  ·  chunk {e['chunk_index']}")
            st.text(e["content"])


# ======================= Sidebar =======================
with st.sidebar:

    # ----- 1) Upload files -----
    st.header("1) Upload CVs")
    files = st.file_uploader("PDF files (at least 8)", type=["pdf"], accept_multiple_files=True)
    if st.button("Upload to Blob", disabled=not files):
        ok, bad = 0, []
        for f in files:
            try:
                data = f.getvalue()
                validate_pdf(f.name, data)                  # Check: real PDF, not empty, under 10 MB
                upload_cv(safe_blob_name(f.name), data)     # Sanitize the name, then upload to Blob
                ok += 1
            except Exception as e:
                bad.append(f"{f.name}: {friendly(e)}")      # Each failed file is reported separately
        if ok:
            st.success(f"Uploaded {ok} file(s)")
        for m in bad:
            st.error(m)

    # ----- 2) Indexing -----
    st.header("2) Index CVs")
    try:
        blobs = list_cvs()
    except Exception as e:
        blobs = []
        st.error(friendly(e))
    st.caption(f"CVs in storage: {len(blobs)}")
    if len(blobs) < 8:
        st.warning("Need at least 8 CVs")

    # Allow indexing the same candidate in two files
    # (disables the email + name + job title duplicate check)
    allow_dup = st.checkbox("Allow same candidate in two files", value=False)

    # Incremental indexing: only processes new or changed files
    if st.button("Index new / changed CVs", disabled=len(blobs) == 0, type="primary"):
        try:
            ensure_index()                                   # Create the index if it doesn't exist
            bar = st.progress(0.0)
            with st.spinner("Indexing..."):
                rep = index_pending(blobs, allow_dup, on_progress=bar.progress)
            st.success(f"Added {len(rep['added'])}, updated {len(rep['updated'])}, "
                       f"skipped {len(rep['skipped'])} (unchanged), chunks written: {rep['chunks']}")
            show_report(rep)
        except Exception as e:
            st.error(friendly(e))

    # Full rebuild (only needed when the index schema changes)
    with st.expander("Rebuild everything (deletes ahmed-cvs-index)"):
        confirm = st.checkbox("I understand: this recreates only ahmed-cvs-index")
        if st.button("Rebuild index", disabled=not confirm or len(blobs) == 0):
            try:
                recreate_index()                             # Deletes ahmed-cvs-index only (guarded in search_service)
                bar = st.progress(0.0)
                with st.spinner("Rebuilding..."):
                    rep = index_pending(blobs, allow_dup, on_progress=bar.progress)
                st.success(f"Rebuilt: {len(rep['added'])} CVs, {rep['chunks']} chunks")
                show_report(rep)
            except Exception as e:
                st.error(friendly(e))

    # ----- Rejected files (not a CV) -----
    try:
        rejected = list_rejected()                           # Read from Blob metadata
    except Exception:
        rejected = {}
    if rejected:
        with st.expander(f"🚫 Rejected files ({len(rejected)})"):
            for n in rejected:
                st.write(f"- {n}")

            # If GPT wrongly rejected a real CV: clear the flag so it gets re-checked
            if st.button("Re-check rejected files"):
                for n in rejected:
                    clear_rejected(n)
                st.rerun()

            # Permanent delete from Blob (requires confirmation, never automatic)
            sure = st.checkbox("I understand: delete these files from Blob permanently")
            if st.button("Delete rejected files from Blob", disabled=not sure):
                for n in rejected:
                    delete_cv_blob(n)
                st.rerun()

    # Clear the conversation
    if st.button("🗑️ New chat"):
        st.session_state.messages = []
        st.rerun()


# ======================= Tools: Candidates / Job Matching / Compare =======================
profiles, err = load_profiles()
if err:
    st.error(f"Could not read the index: {err}")
    st.info("If you just changed the schema, open the sidebar and click 'Rebuild index' once.")

# Chunks per CV (shown in the Candidates table as indexing status)
chunk_counts = get_chunk_counts() if profiles else {}


def label_of(f):
    """Friendly label for a file: candidate name if known, else the file name."""
    for p in profiles:
        if p["file_name"] == f:
            return p.get("candidate_name") or f
    return f


with st.expander(f"🧰 Tools  ·  {len(profiles)} candidates indexed", expanded=False):
    tab_cands, tab_match, tab_cmp = st.tabs(["👥 Candidates", "🎯 Job Matching", "⚖️ Compare"])

    # ---- Tab 1: Candidates + filters ----
    with tab_cands:
        c1, c2, c3, c4 = st.columns(4)
        skill = c1.text_input("Skill contains")
        min_years = c2.number_input("Min years of experience", min_value=0.0, value=0.0, step=1.0)
        title = c3.text_input("Job title contains")
        lang = c4.text_input("Language")

        # Filtering happens in Python on the profiles (small dataset, no performance concern)
        shown = filter_profiles(profiles, skill, min_years if min_years > 0 else None, title, lang)
        st.caption(f"Showing {len(shown)} of {len(profiles)}  ·  total chunks: {sum(chunk_counts.values())}")
        st.dataframe(
            [{
                "File": p["file_name"],
                "Name": p["candidate_name"],
                "Title": p["job_title"],
                "Years": p["years_experience"],
                "Skills": ", ".join(p.get("skills") or []),
                "Languages": ", ".join(p.get("languages") or []),
                "Email": p["email"],
                "Chunks": chunk_counts.get(p["file_name"], 0),
            } for p in shown],
            use_container_width=True,
        )

    # ---- Tab 2: Job Matching ----
    with tab_match:
        jd = st.text_area("Paste a job description", height=180, max_chars=4000, key="jd_text")
        top_n = st.slider("Show top N candidates", 1, max(len(profiles), 1), min(5, max(len(profiles), 1)))
        if st.button("Rank candidates", disabled=not jd.strip() or not profiles, type="primary"):
            try:
                with st.spinner("Matching candidates..."):
                    st.session_state["match_result"] = match_job(jd, profiles)
            except Exception as e:
                st.error(friendly(e))

        # Result is kept in session_state so it survives reruns
        res = st.session_state.get("match_result")
        if res:
            req = res["requirements"]
            st.caption(
                f"Detected role: {req.get('job_title') or '-'}  ·  must-have: "
                f"{', '.join(req.get('must_have_skills') or []) or '-'}  ·  min years: {req.get('min_years') or '-'}"
            )
            st.dataframe(
                [{"Rank": i + 1, "Candidate": r["name"] or r["file_name"], "Title": r["title"], "Match %": r["score"]}
                 for i, r in enumerate(res["ranking"][:top_n])],
                use_container_width=True,
                column_config={
                    "Match %": st.column_config.ProgressColumn("Match %", min_value=0, max_value=100, format="%d")
                },
            )
            for i, r in enumerate(res["ranking"][:top_n]):
                with st.expander(f"#{i + 1}  {r['name'] or r['file_name']}  ·  {r['score']}%"):
                    st.write(r["reason"])
                    st.markdown("**Matched:** " + (", ".join(r["matched"]) or "-"))
                    st.markdown("**Missing:** " + (", ".join(r["missing"]) or "-"))
                    st.caption(f"Source: {r['file_name']}")
            st.caption("Scores are AI estimates based on the indexed profiles and CV excerpts. "
                       "Use them to shortlist, not to decide.")

    # ---- Tab 3: Compare ----
    with tab_cmp:
        picked = st.multiselect(
            "Pick 2 or more candidates",
            options=[p["file_name"] for p in profiles],
            format_func=label_of,
        )
        if len(picked) >= 2:
            # Deterministic table built from structured profiles (no GPT, no hallucination)
            cmp_res = compare_table(picked, profiles)
            st.dataframe(cmp_res["rows"], use_container_width=True)
            st.markdown("**Skills in common:** " + (", ".join(cmp_res["common"]) or "none"))

            # Optional AI step, only when the button is pressed
            if st.button("Add AI experience summary"):
                try:
                    with st.spinner("Summarizing..."):
                        sums = experience_summaries(picked, profiles)
                    for f in picked:
                        st.markdown(f"**{label_of(f)}** ({f}): {sums.get(f) or '-'}")
                except Exception as e:
                    st.error(friendly(e))
        else:
            st.info("Select at least two candidates to compare.")


# ======================= Chat =======================
st.header("3) Chat")
if "messages" not in st.session_state:
    st.session_state.messages = []

# Suggested questions: shown only while the chat is empty
SUGGESTED = [
    "اعرض كل المرشحين وتخصص كل واحد",
    "عرض التعليم للمرشحين",
    "عرض اللغات للمرشحين",
    "كام مرشح عنده 5 سنين خبرة أو أكتر؟",
    "Compare the AI engineer with the pharmacy candidate",
]
if not st.session_state.messages and profiles:
    st.caption("Try one of these:")
    cols = st.columns(len(SUGGESTED))
    for col, s in zip(cols, SUGGESTED):
        if col.button(s, use_container_width=True):
            st.session_state["pending_q"] = s        # picked up by the chat input below
            st.rerun()

# Render previous messages (assistant messages keep their sources + evidence)
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant":
            render_evidence(m.get("sources"), m.get("evidence"))

# New question: typed text, or a clicked suggestion
typed = st.chat_input("Ask about the CVs...", max_chars=3000)
q = typed or st.session_state.pop("pending_q", None)
if q:
    st.session_state.messages.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        sources, evidence = [], None
        try:
            with st.spinner("Thinking..."):
                text, sources, evidence = answer(q, st.session_state.messages[:-1], profiles)
            st.markdown(text)
            render_evidence(sources, evidence)
        except Exception as e:
            text = f"⚠️ {friendly(e)}"                       # Friendly message instead of a crash
            st.error(text)
    # Store sources/evidence with the message so they survive Streamlit reruns
    st.session_state.messages.append(
        {"role": "assistant", "content": text, "sources": sources, "evidence": evidence}
    )