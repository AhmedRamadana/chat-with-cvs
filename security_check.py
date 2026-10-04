import re
from pathlib import Path

import httpx
from azure.storage.blob import BlobServiceClient

import chat_service
import search_service
from config import settings
from errors import friendly

results = []


def record(name: str, ok: bool, detail: str = ""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


# ---------- 1) Secrets are not in the code, and .env is git-ignored ----------
def check_secrets():
    gitignore = Path(".gitignore").read_text(encoding="utf-8") if Path(".gitignore").exists() else ""
    record(".env is listed in .gitignore", ".env" in gitignore.splitlines())

    secrets = {v for k, v in (
        ("key", settings.search_key), ("key", settings.openai_key), ("conn", settings.storage_conn)
    ) if v and len(v) > 12}
    leaked = []
    for f in Path(".").glob("*.py"):
        src = f.read_text(encoding="utf-8", errors="ignore")
        if any(s in src for s in secrets):
            leaked.append(f.name)
    record("No secret value is hard-coded in any .py file", not leaked, ", ".join(leaked))


# ---------- 2) Error messages do not leak secrets or CV data ----------
def check_error_messages():
    secrets = [settings.search_key, settings.openai_key, settings.storage_conn]
    fake = [ValueError("boom"), RuntimeError(f"failed with key {settings.openai_key}"), KeyError("x")]
    msgs = [friendly(e) for e in fake]
    leaked = any(s and s in m for s in secrets for m in msgs)
    record("friendly() never echoes a secret", not leaked)
    record("Unknown errors are shown generically",
           friendly(RuntimeError("secret detail")) == "Unexpected error (RuntimeError).")


# ---------- 3) Blob is private ----------
def check_blob_private():
    client = BlobServiceClient.from_connection_string(settings.storage_conn)
    container = client.get_container_client(settings.storage_container)
    props = container.get_container_properties()
    record("Container public access is disabled", props.public_access is None, str(props.public_access))

    names = [b.name for b in container.list_blobs()][:1]
    if names:
        url = f"{client.url.rstrip('/')}/{settings.storage_container}/{names[0]}"
        status = httpx.get(url, timeout=20).status_code
        record("Anonymous download of a CV is refused", status in (401, 403, 404, 409), f"HTTP {status}")

        
# ---------- 4) The shared-index guard works ----------
def check_index_guard():
    # We call _guard() directly. We never call recreate_index() with a wrong name, on purpose:
    # if the guard were broken, that call could delete a teammate's index.
    original = settings.search_index
    try:
        blocked = True
        for foreign in ("cv-index", "cvs-index"):
            settings.search_index = foreign
            try:
                search_service._guard()
                blocked = False
            except RuntimeError:
                pass
        record("Guard refuses indexes that are not ahmed-cvs-index", blocked)
    finally:
        settings.search_index = original


# ---------- 5) Azure failure simulation (nothing is really shut down) ----------
def check_failures():
    profiles = search_service.get_indexed_cvs()

    # (a) wrong chat deployment name
    original = settings.chat_deployment
    settings.chat_deployment = "deployment-that-does-not-exist"
    try:
        chat_service.answer("ايه تعليم أحمد؟", [], profiles)
        record("Wrong deployment name -> friendly error", False, "no error raised")
    except Exception as e:
        msg = friendly(e)
        record("Wrong deployment name -> friendly error", "deployment" in msg.lower(), msg)
    finally:
        settings.chat_deployment = original

    # (b) empty index message (no Azure call needed)
    text, sources, _ = chat_service.answer("hello", [], [])
    record("Empty index -> clear message, no crash", "No CVs are indexed" in text and sources == [])

    # (c) bad key
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    try:
        bad = SearchClient(settings.search_endpoint, settings.search_index, AzureKeyCredential("wrong-key"))
        list(bad.search("*", top=1))
        record("Wrong Search key -> friendly error", False, "no error raised")
    except Exception as e:
        msg = friendly(e)
        record("Wrong Search key -> friendly error", "wrong-key" not in msg, msg)


if __name__ == "__main__":
    for fn in (check_secrets, check_error_messages, check_blob_private, check_index_guard, check_failures):
        try:
            fn()
        except Exception as e:
            record(f"{fn.__name__} crashed", False, f"{type(e).__name__}")
    print(f"\n{sum(results)}/{len(results)} checks passed")