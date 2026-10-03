"""Run a prompt on a split of the golden set. One row per item, always.

Usage (from the repo root):
    python harness/runner.py --prompt prompts/classifier_v2.txt --split dev
    python harness/runner.py --prompt prompts/classifier_v2.txt --split test
    python harness/runner.py --prompt prompts/classifier_v2.txt --split dev --dry-run   # no API call

Output: results/<prompt name>_<split>.jsonl  (one row per item)
Re-running resumes: items that already have a successful row are skipped,
items that failed are retried.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import CLASSIFIER_SCHEMA, LABELS  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "instagram_labels_split_140_dev_60_test.xlsx"
API_URL = "https://api.groq.com/openai/v1/chat/completions"
SYSTEM_MESSAGE = (
    "You are an Instagram comment classification system. Follow the "
    "classification instructions exactly. Return only a json object "
    "containing the label and reason."
)
MAX_RETRIES = 6


def build_prompt(template: str, comment: str) -> str:
    if "{{COMMENT}}" in template:
        return template.replace("{{COMMENT}}", comment.strip())
    return template.rstrip() + "\n\nComment:\n" + comment.strip()


def call_model(api_key, model, prompt):
    """Return (label, reason, usage). Raises RuntimeError after all retries."""
    payload = {
        "model": model,
        "temperature": 0,
        "include_reasoning": False,
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "instagram_comment_classification",
                "strict": True,
                "schema": CLASSIFIER_SCHEMA,
            },
        },
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error = "unknown error"
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(API_URL, headers=headers, json=payload, timeout=60)
            if r.status_code == 200:
                data = r.json()
                content = json.loads(data["choices"][0]["message"]["content"])
                if content.get("label") not in LABELS:
                    raise ValueError(f"bad label: {content.get('label')!r}")
                return content["label"], content.get("reason", ""), data.get("usage", {})
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            # json_validate_failed = the model returned an empty/invalid answer: random, retry it
            flaky = r.status_code == 400 and "json_validate_failed" in r.text
            if r.status_code not in (429, 500, 502, 503, 504) and not flaky:
                break  # not worth retrying (bad key, truly bad request, ...)
            wait = 1 if flaky else float(r.headers.get("retry-after", 2 ** attempt))
        except (requests.RequestException, ValueError, KeyError, json.JSONDecodeError) as e:
            last_error = f"{type(e).__name__}: {e}"
            wait = 2 ** attempt
        time.sleep(min(wait, 60))
    raise RuntimeError(last_error)


def load_done(path: Path) -> dict:
    """Rows already written, keyed by item_id (last row wins)."""
    done = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["item_id"]] = row
    return done


def summarize(rows):
    n = len(rows)
    ok = [r for r in rows if r["error"] is None]
    correct = sum(r["correct"] is True for r in ok)
    print(f"\nItems: {n} | answered: {len(ok)} | failed: {n - len(ok)}")
    print(f"Correct: {correct}/{n} ({100 * correct / n:.1f}%)  (failed items count as wrong)")
    for lab in LABELS:
        sub = [r for r in rows if r["gold_label"] == lab]
        c = sum(r["correct"] is True for r in sub)
        print(f"  gold {lab:<12} {c}/{len(sub)}")
    tokens = sum((r.get("total_tokens") or 0) for r in ok)
    print(f"Total tokens: {tokens}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True, help="path to prompt file, e.g. prompts/classifier_v2.txt")
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--model", default=None, help="default: $GROQ_MODEL or openai/gpt-oss-20b")
    ap.add_argument("--limit", type=int, default=None, help="only the first N items (for quick tests)")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    ap.add_argument("--dry-run", action="store_true", help="no API call; fake predictions to test the pipeline")
    args = ap.parse_args()

    load_dotenv(BASE_DIR / ".env")
    api_key = os.getenv("GROQ_API_KEY")
    model = args.model or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    if not api_key and not args.dry_run:
        sys.exit("ERROR: GROQ_API_KEY not found in .env (or use --dry-run)")

    prompt_path = Path(args.prompt)
    if not prompt_path.is_absolute():
        prompt_path = BASE_DIR / prompt_path
    template = prompt_path.read_text(encoding="utf-8")
    if not template.strip():
        sys.exit(f"ERROR: prompt file is empty: {prompt_path}")
    version = prompt_path.stem

    df = pd.read_excel(DATA_FILE, sheet_name=f"{args.split}_set")
    missing = {"item_id", "comment_text", "final_label"} - set(df.columns)
    if missing:
        sys.exit(f"ERROR: missing columns: {missing}")
    if args.limit:
        df = df.head(args.limit)

    out = BASE_DIR / "results" / f"{version}_{args.split}{'_dryrun' if args.dry_run else ''}.jsonl"
    out.parent.mkdir(exist_ok=True)
    done = load_done(out)
    print(f"{len(df)} items | prompt={version} | split={args.split} | model={model}")
    print(f"Already done (kept): {sum(r['error'] is None for r in done.values())}")

    rows = []
    for i, item in enumerate(df.itertuples(index=False), 1):
        prev = done.get(item.item_id)
        if prev and prev["error"] is None:
            rows.append(prev)
            continue
        row = {
            "item_id": item.item_id,
            "comment_text": item.comment_text,
            "gold_label": item.final_label,
            "predicted_label": None,
            "reason": None,
            "correct": False,
            "error": None,
            "latency_ms": None,
            "model": model,
            "prompt_version": version,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }
        t0 = time.perf_counter()
        try:
            if args.dry_run:
                label, reason, usage = "Positive", "dry run", {}
            else:
                label, reason, usage = call_model(
                    api_key, model, build_prompt(template, str(item.comment_text))
                )
            row.update(
                predicted_label=label,
                reason=reason,
                correct=(label == item.final_label),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
        except RuntimeError as e:
            row["error"] = str(e)  # failed items still get a row
            print(f"  [{i}] {item.item_id} FAILED: {e}")
        row["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        rows.append(row)
        done[item.item_id] = row
        # rewrite the file after every item so a crash never loses work
        out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        if not args.dry_run:
            time.sleep(args.delay)

    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"Saved: {out}")
    summarize(rows)


if __name__ == "__main__":
    main()