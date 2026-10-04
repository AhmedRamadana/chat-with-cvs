import hashlib
import io
import json
import re

from openai import AzureOpenAI
from pypdf import PdfReader

from config import settings

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
EMBED_BATCH = 16
MAX_FILE_MB = 10
MIN_TEXT_CHARS = 100

_client = AzureOpenAI(
    azure_endpoint=settings.openai_endpoint,
    api_key=settings.openai_key,
    api_version=settings.openai_api_version,
    timeout=60,
    max_retries=4,  # الـ SDK بيعيد المحاولة تلقائياً عند 429 / 5xx
)


# ---------- Validation ----------
def safe_blob_name(name: str) -> str:
    name = re.sub(r"[^\w\s.\-()]", "_", name, flags=re.UNICODE)
    return re.sub(r"\s+", " ", name).strip()


def validate_pdf(name: str, data: bytes) -> None:
    if not name.lower().endswith(".pdf"):
        raise ValueError(f"{name}: only PDF files are allowed")
    if not data:
        raise ValueError(f"{name}: file is empty")
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"{name}: file is larger than {MAX_FILE_MB} MB")
    if not data.startswith(b"%PDF"):
        raise ValueError(f"{name}: not a valid PDF")


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------- Extraction ----------
def extract_text(pdf_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF is password-protected")
        pages = [(p.extract_text() or "") for p in reader.pages]
    except ValueError:
        raise
    except Exception:
        raise ValueError("PDF is corrupted or unreadable")
    text = "\n".join(pages)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + size // 2, end)
            if cut != -1:
                end = cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


# ---------- Structured profile ----------
PROFILE_PROMPT = """Extract a candidate profile from this document. Return ONLY JSON:
{
  "is_cv": true,
  "candidate_name": "",
  "email": "",
  "phone": "",
  "job_title": "",
  "years_experience": 0,
  "skills": [],
  "languages": [],
  "education": ""
}
Rules: use "" or [] or null when missing; never invent data. years_experience is total professional
years as a number (estimate from dates, null if unclear). skills = technical/professional skills, short names.
languages = spoken languages (e.g. Arabic, English). job_title = the candidate's main/current title in English.
education = highest degree + field + university in one short line.
is_cv = true ONLY if the document is the resume/CV of one person. Set false for anything else
(use cases, reports, manuals, articles, contracts, slides, etc.)."""



CV_KEYWORDS = [
    "experience", "education", "skills", "summary", "objective", "projects",
    "certifications", "employment", "references", "languages", "curriculum vitae", "resume",
    "خبرة", "خبرات", "تعليم", "مهارات", "سيرة ذاتية",
]


def looks_like_cv(text: str, gpt_flag) -> bool:
    """بنجمع رأي GPT مع الكلمات المفتاحية عشان نقلل الرفض الغلط."""
    low = text.lower()
    hits = sum(1 for k in CV_KEYWORDS if k in low)
    if gpt_flag is True:
        return True
    if gpt_flag is False:
        return hits >= 5      # GPT قال لأ: مش هنعارضه إلا لو الملف شكله CV جداً
    return hits >= 1          # GPT ما ردش (فشل): نعتمد على الكلمات


def extract_profile(text: str) -> dict:
    try:
        resp = _client.chat.completions.create(
            model=settings.chat_deployment,
            messages=[
                {"role": "system", "content": PROFILE_PROMPT},
                {"role": "user", "content": text[:12000]},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        p = json.loads(resp.choices[0].message.content)
    except Exception:
        p = {}  # الـ profile تحسين، فشله ما يوقفش الـ indexing

    years = p.get("years_experience")
    try:
        years = float(years) if years is not None else None
    except (TypeError, ValueError):
        years = None

    def clean_list(v):
        v = v if isinstance(v, list) else []
        return sorted({str(x).strip().lower() for x in v if str(x).strip()})

    raw_flag = p.get("is_cv")
    is_cv_flag = raw_flag if isinstance(raw_flag, bool) else None

    return {
        "is_cv": is_cv_flag,                      # <-- سطر جديد
        "candidate_name": str(p.get("candidate_name") or "").strip(),
        "email": str(p.get("email") or "").strip().lower(),
        "phone": str(p.get("phone") or "").strip(),
        "job_title": str(p.get("job_title") or "").strip(),
        "years_experience": years,
        "skills": clean_list(p.get("skills")),
        "languages": clean_list(p.get("languages")),
        "education": str(p.get("education") or "").strip(),
    }


# ---------- Embeddings + documents ----------
def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors = []
    for i in range(0, len(texts), EMBED_BATCH):
        resp = _client.embeddings.create(
            model=settings.embedding_deployment, input=texts[i : i + EMBED_BATCH]
        )
        vectors.extend(item.embedding for item in resp.data)
    return vectors


def _doc_id(file_name: str, idx: int) -> str:
    return hashlib.md5(f"{file_name}-{idx}".encode()).hexdigest()


def analyze_cv(file_name: str, data: bytes) -> dict:
    text = extract_text(data)
    if len(text) < MIN_TEXT_CHARS:
        raise ValueError(f"{file_name}: no extractable text (scanned PDF?)")
    profile = extract_profile(text)
    return {
        "file_name": file_name,
        "text": text,
        "hash": content_hash(data),
        "profile": profile,
        "is_cv": looks_like_cv(text, profile.get("is_cv")),   # <-- جديد
    }


def build_documents(a: dict) -> list[dict]:
    chunks = chunk_text(a["text"])
    contextual = [f"[CV: {a['file_name']}]\n{c}" for c in chunks]
    vectors = embed_texts(contextual)
    p = a["profile"]
    return [
        {
            "id": _doc_id(a["file_name"], i),
            "file_name": a["file_name"],
            "chunk_index": i,
            "content": contextual[i],
            "content_vector": vectors[i],
            "content_hash": a["hash"],
            "candidate_name": p["candidate_name"],
            "email": p["email"],
            "phone": p["phone"],
            "job_title": p["job_title"],
            "years_experience": p["years_experience"],
            "skills": p["skills"],
            "languages": p["languages"],
            "education": p["education"],
        }
        for i in range(len(chunks))
    ]