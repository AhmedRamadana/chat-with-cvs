from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex, SimpleField, SearchableField, SearchField, SearchFieldDataType,
    VectorSearch, HnswAlgorithmConfiguration, VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery
from openai import AzureOpenAI

from config import settings

EMBED_DIM = 1536
OUR_INDEX = "ahmed-cvs-index"

_cred = AzureKeyCredential(settings.search_key)
_index_client = SearchIndexClient(settings.search_endpoint, _cred)
_search_client = SearchClient(settings.search_endpoint, settings.search_index, _cred)
_openai = AzureOpenAI(
    azure_endpoint=settings.openai_endpoint,
    api_key=settings.openai_key,
    api_version=settings.openai_api_version,
    timeout=60,
    max_retries=4,
)

S = SearchFieldDataType


def _guard():
    # حماية الـ index المشترك: مسموح نلمس index واحد بالاسم بس
    if settings.search_index != OUR_INDEX:
        raise RuntimeError(f"Safety check: refusing to touch an index not named {OUR_INDEX}")


def _build_index() -> SearchIndex:
    fields = [
        SimpleField(name="id", type=S.String, key=True),
        SearchableField(name="content", type=S.String),
        SearchableField(name="file_name", type=S.String, filterable=True),
        SimpleField(name="chunk_index", type=S.Int32, filterable=True),
        SimpleField(name="content_hash", type=S.String, filterable=True),
        SearchableField(name="candidate_name", type=S.String, filterable=True),
        SearchableField(name="email", type=S.String, filterable=True),
        SimpleField(name="phone", type=S.String),
        SearchableField(name="job_title", type=S.String, filterable=True),
        SimpleField(name="years_experience", type=S.Double, filterable=True),
        SearchField(name="skills", type=S.Collection(S.String), searchable=True, filterable=True),
        SearchField(name="languages", type=S.Collection(S.String), searchable=True, filterable=True),
        SimpleField(name="education", type=S.String),
        SearchField(
            name="content_vector",
            type=S.Collection(S.Single),
            searchable=True,
            vector_search_dimensions=EMBED_DIM,
            vector_search_profile_name="vec-profile",
        ),
    ]
    vs = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw-config")],
        profiles=[VectorSearchProfile(name="vec-profile", algorithm_configuration_name="hnsw-config")],
    )
    return SearchIndex(name=settings.search_index, fields=fields, vector_search=vs)


def ensure_index() -> None:
    _guard()
    if settings.search_index not in list(_index_client.list_index_names()):
        _index_client.create_index(_build_index())


def recreate_index() -> None:
    _guard()
    if settings.search_index in list(_index_client.list_index_names()):
        _index_client.delete_index(settings.search_index)
    _index_client.create_index(_build_index())


def upload_documents(docs: list[dict]) -> int:
    ok = 0
    for i in range(0, len(docs), 100):
        results = _search_client.upload_documents(documents=docs[i : i + 100])
        ok += sum(1 for r in results if r.succeeded)
    return ok


def delete_cv(file_name: str) -> None:
    safe = file_name.replace("'", "''")
    ids = [
        {"id": r["id"]}
        for r in _search_client.search("*", filter=f"file_name eq '{safe}'", select=["id"], top=1000)
    ]
    if ids:
        _search_client.delete_documents(documents=ids)


def get_indexed_cvs() -> list[dict]:
    """بروفايل واحد لكل CV (chunk رقم 0). ده اللي بيضمن إن مفيش CV يتفوّت."""
    try:
        rows = _search_client.search(
            "*",
            filter="chunk_index eq 0",
            select=["file_name", "content_hash", "candidate_name", "email", "phone",
                    "job_title", "years_experience", "skills", "languages", "education"],
            top=1000,
        )
        return sorted((dict(r) for r in rows), key=lambda r: r["file_name"].lower())
    except ResourceNotFoundError:
        return []


def get_chunk_counts() -> dict[str, int]:
    """How many chunks each CV has in the index (for the status table)."""
    try:
        counts: dict[str, int] = {}
        for r in _search_client.search("*", select=["file_name"], top=1000):
            counts[r["file_name"]] = counts.get(r["file_name"], 0) + 1
        return counts
    except ResourceNotFoundError:
        return {}


def filter_profiles(profiles, skill="", min_years=None, title="", language=""):
    out = []
    for p in profiles:
        if skill and not any(skill.lower() in s for s in (p.get("skills") or [])):
            continue
        if min_years is not None and (p.get("years_experience") or 0) < min_years:
            continue
        if title and title.lower() not in (p.get("job_title") or "").lower():
            continue
        if language and not any(language.lower() in l for l in (p.get("languages") or [])):
            continue
        out.append(p)
    return out


def search(query: str, top: int = 8, file_name: str | None = None) -> list[dict]:
    """Hybrid search. If file_name is given, search only inside that CV (OData filter)."""
    filt = None
    if file_name:
        safe = file_name.replace("'", "''")   # escape single quotes for OData
        filt = f"file_name eq '{safe}'"

    vec = _openai.embeddings.create(model=settings.embedding_deployment, input=query).data[0].embedding
    results = _search_client.search(
        search_text=query,
        vector_queries=[VectorizedQuery(vector=vec, k_nearest_neighbors=top, fields="content_vector")],
        filter=filt,
        select=["file_name", "content", "chunk_index"],
        top=top,
    )
    return [dict(r) for r in results]