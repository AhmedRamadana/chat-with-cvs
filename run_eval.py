import json
import sys
import time
from collections import defaultdict

from chat_service import answer
from errors import friendly
from eval_cases import CASES
from search_service import get_indexed_cvs

PAUSE_SECONDS = 1.0   # small pause between calls: the OpenAI deployment is shared with the team


def has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def check(case: dict, text: str, sources: list, n_profiles: int) -> list[str]:
    """Return a list of failure reasons (empty list = pass)."""
    fails, low = [], text.lower()

    for group in case.get("all_of", []):
        if not any(term.lower() in low for term in group):
            fails.append(f"missing any of {group}")
    for bad in case.get("none_of", []):
        if bad.lower() in low:
            fails.append(f"should not contain '{bad}'")

    expected = case.get("sources")
    if expected == "none" and sources:
        fails.append(f"expected no sources, got {len(sources)}")
    if expected == "some" and not sources:
        fails.append("expected sources, got none")
    if expected == "all" and len(sources) < n_profiles:
        fails.append(f"coverage: {len(sources)}/{n_profiles} CVs cited")

    if case.get("clarify"):
        asks = text.rstrip().endswith(("?", "؟"))
        if not asks or sources:
            fails.append("expected a clarifying question with no sources")

    lang = case.get("lang")
    if lang == "ar" and not has_arabic(text):
        fails.append("expected an Arabic answer")
    if lang == "en" and has_arabic(text):
        fails.append("expected an English answer")
    return fails


def run_case(case: dict, profiles: list[dict]) -> dict:
    history, text, sources = [], "", []
    start = time.time()
    try:
        for turn in case["turns"]:
            text, sources, _ = answer(turn, history, profiles)
            history += [{"role": "user", "content": turn}, {"role": "assistant", "content": text}]
            time.sleep(PAUSE_SECONDS)
        fails = check(case, text, sources, len(profiles))
    except Exception as e:
        fails, text = [f"error: {friendly(e)}"], ""
    return {"id": case["id"], "group": case["group"], "question": case["turns"][-1],
            "passed": not fails, "fails": fails, "sources": len(sources),
            "seconds": round(time.time() - start, 1), "answer": text}


def main():
    profiles = get_indexed_cvs()
    if not profiles:
        sys.exit("Index is empty. Index the CVs first.")

    only = set(sys.argv[1:])   # optional: python run_eval.py H1 H2
    cases = [c for c in CASES if not only or c["id"] in only]
    print(f"Running {len(cases)} cases against {len(profiles)} indexed CVs...\n")

    results = []
    for c in cases:
        r = run_case(c, profiles)
        results.append(r)
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"[{mark}] {r['id']:<3} {r['seconds']:>5}s  {r['question'][:55]}")
        for f in r["fails"]:
            print(f"        -> {f}")

    by_group = defaultdict(list)
    for r in results:
        by_group[r["group"]].append(r["passed"])
    print("\n" + "=" * 46)
    for g, vals in by_group.items():
        print(f"{g:<15} {sum(vals)}/{len(vals)}  ({100 * sum(vals) // len(vals)}%)")
    total = sum(r["passed"] for r in results)
    avg = sum(r["seconds"] for r in results) / len(results)
    print("=" * 46)
    print(f"TOTAL {total}/{len(results)} ({100 * total // len(results)}%)   avg latency {avg:.1f}s")

    # Full answers are saved for manual review. They contain CV data: do not share this file.
    with open("eval_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("Details saved to eval_results.json")


if __name__ == "__main__":
    main()