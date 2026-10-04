from blob_service import download_cv, list_rejected, mark_rejected
from ingestion import analyze_cv, build_documents, content_hash
from search_service import delete_cv, get_indexed_cvs, upload_documents
from errors import friendly


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _candidate_key(email: str, name: str, title: str):
    e, n, t = _norm(email), _norm(name), _norm(title)
    return (e, n, t) if e and n and t else None


def index_pending(blob_names, allow_duplicate_candidates=False, on_progress=None) -> dict:
    indexed = {c["file_name"]: c for c in get_indexed_cvs()}
    by_hash = {c["content_hash"]: c["file_name"] for c in indexed.values()}
    by_candidate = {}
    for c in indexed.values():
        k = _candidate_key(c.get("email"), c.get("candidate_name"), c.get("job_title"))
        if k:
            by_candidate[k] = c["file_name"]

    try:
        rejected = list_rejected()      # (جديد) الملفات المرفوضة سابقاً
    except Exception:
        rejected = {}

    report = {"added": [], "updated": [], "skipped": [], "duplicates": [],
              "rejected": [], "rejected_known": [], "failed": [], "chunks": 0}

    for i, name in enumerate(blob_names):
        try:
            data = download_cv(name)
            h = content_hash(data)

            if name in indexed and indexed[name]["content_hash"] == h:
                report["skipped"].append(name)

            elif rejected.get(name) == h:                       # (جديد) اترفض قبل كده بنفس المحتوى
                report["rejected_known"].append(name)

            elif h in by_hash and by_hash[h] != name:
                report["duplicates"].append(f"{name}  (identical file to {by_hash[h]})")

            else:
                a = analyze_cv(name, data)

                if not a["is_cv"]:                              # (جديد) مش CV
                    mark_rejected(name, h)
                    report["rejected"].append(name)
                else:
                    p = a["profile"]
                    key = _candidate_key(p["email"], p["candidate_name"], p["job_title"])
                    other = by_candidate.get(key) if key else None

                    if other and other != name and not allow_duplicate_candidates:
                        report["duplicates"].append(
                            f"{name}  (same email + name + job title as {other})"
                        )
                    else:
                        is_update = name in indexed
                        if is_update:
                            delete_cv(name)
                        docs = build_documents(a)
                        report["chunks"] += upload_documents(docs)
                        report["updated" if is_update else "added"].append(name)
                        by_hash[h] = name
                        if key:
                            by_candidate[key] = name
        except Exception as e:
            report["failed"].append(f"{name}: {friendly(e)}")

        if on_progress:
            on_progress((i + 1) / len(blob_names))

    return report