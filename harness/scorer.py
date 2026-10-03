"""Score one or more result files written by runner.py.

Usage (from the repo root):
    python harness/scorer.py results/classifier_v2_dev.jsonl
    python harness/scorer.py results/classifier_v2_dev.jsonl results/classifier_v3_dev.jsonl   # side by side

For each file it prints: counts, accuracy, per-label precision/recall/F1, confusion matrix,
failed items, latency, tokens and cost. It also saves results/metrics_<file name>.json.
Failed items (no prediction) always count as wrong, so every item is in the score.
"""
import json
import statistics
import sys
from pathlib import Path

from schema import LABELS

# Groq list price for openai/gpt-oss-20b, USD per 1M tokens (checked Oct 2026; prices change).
PRICE_INPUT_PER_M = 0.075
PRICE_OUTPUT_PER_M = 0.30


def load_rows(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    k = min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))
    return values[k]


def compute_metrics(rows):
    n = len(rows)
    ok = [r for r in rows if r.get("error") is None and r.get("predicted_label")]
    failed = [r for r in rows if r not in ok]
    correct = sum(r["predicted_label"] == r["gold_label"] for r in ok)

    # confusion matrix: gold (rows) x predicted (columns); failed items go in a "FAILED" column
    cols = LABELS + ["FAILED"]
    matrix = {g: {c: 0 for c in cols} for g in LABELS}
    for r in rows:
        pred = r["predicted_label"] if r in ok else "FAILED"
        matrix[r["gold_label"]][pred] += 1

    per_label = {}
    for lab in LABELS:
        tp = matrix[lab][lab]
        gold_n = sum(matrix[lab].values())
        pred_n = sum(matrix[g][lab] for g in LABELS)
        prec = tp / pred_n if pred_n else 0.0
        rec = tp / gold_n if gold_n else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per_label[lab] = {
            "gold_count": gold_n, "correct": tp, "predicted_count": pred_n,
            "precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3),
        }
    macro_f1 = round(sum(v["f1"] for v in per_label.values()) / len(LABELS), 3)

    lat = [r["latency_ms"] for r in ok if r.get("latency_ms") is not None]
    pt = sum(r.get("prompt_tokens") or 0 for r in ok)
    ct = sum(r.get("completion_tokens") or 0 for r in ok)
    cost = pt / 1e6 * PRICE_INPUT_PER_M + ct / 1e6 * PRICE_OUTPUT_PER_M
    per_item_cost = cost / len(ok) if ok else 0.0

    return {
        "items": n, "answered": len(ok), "failed": len(failed),
        "failed_ids": [r["item_id"] for r in failed],
        "correct": correct, "accuracy_pct": pct(correct, n),
        "macro_f1": macro_f1, "per_label": per_label, "confusion_matrix": matrix,
        "latency_ms": {
            "mean": round(statistics.mean(lat), 1) if lat else None,
            "median": round(statistics.median(lat), 1) if lat else None,
            "p95": round(percentile(lat, 95), 1) if lat else None,
        },
        "tokens": {"prompt": pt, "completion": ct, "total": pt + ct},
        "cost_usd": {
            "this_run": round(cost, 5),
            "per_item": round(per_item_cost, 7),
            "per_1k_requests": round(per_item_cost * 1000, 4),
            "per_100k_requests_(100x)": round(per_item_cost * 100_000, 2),
        },
    }


def print_report(name, m):
    print(f"\n=== {name} ===")
    print(f"Items: {m['items']} | answered: {m['answered']} | failed: {m['failed']}"
          + (f" ({', '.join(m['failed_ids'])})" if m["failed_ids"] else ""))
    print(f"Correct: {m['correct']}/{m['items']} ({m['accuracy_pct']}%) | macro-F1: {m['macro_f1']}")
    print(f"\n{'label':<13}{'gold':>5}{'ok':>5}{'recall':>9}{'precision':>11}{'F1':>7}")
    for lab, v in m["per_label"].items():
        print(f"{lab:<13}{v['gold_count']:>5}{v['correct']:>5}{pct(v['correct'], v['gold_count']):>8}%"
              f"{v['precision'] * 100:>10.1f}%{v['f1']:>7.2f}")
    print("\nConfusion matrix (rows = gold label, columns = predicted):")
    cols = LABELS + ["FAILED"]
    print(f"{'':<13}" + "".join(f"{c:>13}" for c in cols))
    for g in LABELS:
        print(f"{g:<13}" + "".join(f"{m['confusion_matrix'][g][c]:>13}" for c in cols))
    lat, tok, cost = m["latency_ms"], m["tokens"], m["cost_usd"]
    print(f"\nLatency per item (ms): mean {lat['mean']}, median {lat['median']}, p95 {lat['p95']}")
    print(f"Tokens: {tok['total']} (prompt {tok['prompt']}, completion {tok['completion']})")
    print(f"Cost: ${cost['this_run']} this run | ${cost['per_1k_requests']} per 1k requests"
          f" | ${cost['per_100k_requests_(100x)']} per 100k requests (100x)")


def print_comparison(names, metrics):
    print("\n=== Side by side ===")
    print(f"{'run':<28}{'correct':>10}{'acc':>8}{'macro-F1':>10}" + "".join(f"{l[:6] + ' rec':>12}" for l in LABELS))
    for name, m in zip(names, metrics):
        recs = "".join(f"{pct(m['per_label'][l]['correct'], m['per_label'][l]['gold_count']):>11}%" for l in LABELS)
        print(f"{name:<28}{str(m['correct']) + '/' + str(m['items']):>10}{m['accuracy_pct']:>7}%{m['macro_f1']:>10}{recs}")


def main():
    paths = sys.argv[1:]
    if not paths:
        sys.exit(__doc__)
    names, all_metrics = [], []
    for p in paths:
        rows = load_rows(p)
        m = compute_metrics(rows)
        name = Path(p).stem
        print_report(name, m)
        out = Path(p).with_name(f"metrics_{name}.json")
        out.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved: {out}")
        names.append(name)
        all_metrics.append(m)
    if len(paths) > 1:
        print_comparison(names, all_metrics)


if __name__ == "__main__":
    main()
