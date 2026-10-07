"""Language detection and fixed replies.

Input is classified as: "ar", "en", "mixed" (Arabic + English words) or "franco"
(Egyptian Arabic written with Latin letters and digits: 3 = ع, 7 = ح, 5 = خ, 2 = ء, 8 = غ, 9 = ق, 6 = ط).

Reply language rule:  Arabic -> Arabic | English -> English | mixed -> mixed | Franco -> English.
No Azure imports here, so it can be tested offline.
"""
import re

_ARABIC = re.compile(r"[\u0600-\u06ff]")
_WORD = re.compile(r"[a-z0-9']+")

# A Franco-style word: Latin letters with one of the Franco digits followed by a letter (3ando, 7aga, ba3d, ta7lil).
_FRANCO_DIGIT_WORD = re.compile(r"^[a-z]*[235-9][a-z]+$")

# English / tech tokens that look like the pattern above but are not Franco.
_NOT_FRANCO = {"3d", "3ds", "2fa", "b2b", "b2c", "h2o", "k8s", "p2p", "w3c", "e2e", "i2c", "m2m", "o2o", "g2g", "s3a", "x264"}
_UNIT_WORD = re.compile(r"^\d+(yrs?|years?|y|k|m|kb|mb|gb|tb|d|st|nd|rd|th|x|s|h|hz|px)$")

# One of these alone is enough to call the text Franco (rarely English words).
_STRONG = {
    "meen", "ezay", "ezzay", "ayez", "ayza", "lessa", "khebra", "khebrt", "e7na", "elly",
    "ba3d", "delwa2ty", "dlwa2ty", "7aga", "shoghl", "sheghl", "mafish", "mafeesh", "mafesh",
    "afdal", "aktar", "akter", "seneen", "sanawat", "msh", "ana", "enta", "enty",
}
# Need two of these (they can be English words or names).
_WEAK = {"el", "w", "fe", "fi", "de", "da", "di", "ya", "ma", "law", "lw", "hwa", "hya", "homa",
         "mesh", "kam", "fen", "feen", "leh", "ely", "eh", "kol", "ahsan", "men"}
_STRONG.discard("ana"); _STRONG.discard("enta"); _STRONG.discard("enty")
_WEAK.update({"ana", "enta", "enty"})


def has_arabic(text: str) -> bool:
    return bool(_ARABIC.search(text or ""))


def is_franco(text: str) -> bool:
    low = (text or "").lower()
    if has_arabic(low):
        return False
    strong = weak = 0
    for tok in _WORD.findall(low):
        if tok in _NOT_FRANCO or _UNIT_WORD.match(tok):
            continue
        if _FRANCO_DIGIT_WORD.match(tok):
            return True
        if tok in _STRONG:
            strong += 1
        elif tok in _WEAK:
            weak += 1
    return strong >= 1 or weak >= 2


_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z']{2,}")   # English-looking words of 3+ letters


def is_mixed(text: str) -> bool:
    """Arabic text that also contains at least two English words (e.g. "مين عنده experience في Deep Learning؟").
    A single English term ("مين عنده خبرة في Python؟") is still treated as plain Arabic."""
    return has_arabic(text) and len(_LATIN_WORD.findall(text or "")) >= 2


def _classify(text: str) -> str:
    if has_arabic(text):
        return "mixed" if is_mixed(text) else "ar"
    return "franco" if is_franco(text) else "en"


def detect_language(text: str, history: list[dict] | None = None) -> str:
    """Language of the INPUT: "ar" | "en" | "mixed" | "franco".
    Very short, unclear messages (1-2 Latin words, like "Ahmed") reuse the previous user message's language."""
    text = (text or "").strip()
    lang = _classify(text)
    if lang == "en" and len(text.split()) <= 2 and history:
        last_user = next((m["content"] for m in reversed(history) if m.get("role") == "user"), None)
        if last_user:
            return _classify(last_user)
    return lang


def reply_language(text: str, history: list[dict] | None = None) -> str:
    """Language of the REPLY: "ar" | "en" | "mixed". Franco input is answered in English."""
    lang = detect_language(text, history)
    return "en" if lang == "franco" else lang


# Added at the END of the user message sent to the model, so it cannot be ignored or guessed.
REPLY_INSTRUCTION = {
    "ar": "Reply in Arabic, matching the user's dialect (Egyptian colloquial or Modern Standard). "
          "Keep file names, emails and technical terms (Python, SQL, ...) as written.",
    "en": "Reply in English only (even if the user wrote in Franco-Arabic, i.e. Arabic in Latin letters).",
    "mixed": "The user mixed Arabic and English. Reply in the same natural Arabic-English mix (code-switching): "
             "Arabic sentence structure with English words, phrases and technical terms mixed in, "
             "e.g. 'Ahmed عنده experience في Python'. Do not translate everything into Arabic or into English. "
             "Keep file names, emails and technical terms as written.",
}

MESSAGES = {
    "out_of_scope": {
        "ar": "أقدر أجاوب بس على أسئلة عن السير الذاتية المرفوعة (المرشحين، مهاراتهم، خبراتهم...).",
        "en": "I can only answer questions about the uploaded CVs (candidates, skills, experience...).",
        "mixed": "أقدر أجاوب بس على questions عن الـ CVs المرفوعة (candidates, skills, experience...).",
    },
    "no_index": {
        "ar": "لسه مفيش CVs مفهرسة. ارفع الـ CVs واضغط 'Index new / changed CVs' الأول.",
        "en": "No CVs are indexed yet. Upload CVs and click 'Index new / changed CVs' first.",
        "mixed": "لسه مفيش CVs indexed. ارفع الـ CVs واضغط 'Index new / changed CVs' الأول.",
    },
    "clarify_best": {
        "ar": "الأحسن لأنهي وظيفة أو بأي معيار؟ مثلاً: {examples}؟",
        "en": "Best for which role or criteria? For example: {examples}?",
        "mixed": "الأحسن لأنهي role أو بأي criteria؟ مثلاً: {examples}؟",
    },
}
OR_WORD = {"ar": " أو ", "en": " or ", "mixed": " أو "}
FALLBACK_EXAMPLE = {"ar": "مجال معين", "en": "a specific role", "mixed": "specific role"}