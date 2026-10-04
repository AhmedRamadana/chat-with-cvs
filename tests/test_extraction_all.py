from blob_service import list_cvs, download_cv
from ingestion import extract_text, chunk_text

print(f"{'File':<62} {'Chars':>6} {'Chunks':>6}")
print("-" * 76)

for name in list_cvs():
    try:
        text = extract_text(download_cv(name))
        chunks = chunk_text(text)
        flag = "" if len(text) > 300 else "  ⚠️ little/no text"
        print(f"{name[:60]:<62} {len(text):>6} {len(chunks):>6}{flag}")
    except Exception as e:
        print(f"{name[:60]:<62} ❌ {e}")

# عينة من أول ملف عشان نفحص جودة النص بعينينا
first = list_cvs()[0]
print(f"\n--- Sample text from: {first} ---")
print(extract_text(download_cv(first))[:800])