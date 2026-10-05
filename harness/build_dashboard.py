"""Build dashboard/index.html from the results. Run it again after every new scorer run.

    python harness/scorer.py results/classifier_v2_dev.jsonl      # makes results/metrics_*.json
    python harness/build_dashboard.py                             # makes dashboard/index.html

Open dashboard/index.html in any browser. Nothing else to install.
"""
import argparse
import datetime
import json
import re
from pathlib import Path

import pandas as pd
from sklearn.metrics import cohen_kappa_score

BASE = Path(__file__).resolve().parent.parent
DATA_FILE = BASE / "data" / "instagram_labels_split_140_dev_60_test.xlsx"
LABELS = ["Positive", "Humour", "Hate Speech"]
MODEL = "openai/gpt-oss-20b"
PRICE = {"in": 0.075, "out": 0.30, "checked": "Oct 2026"}

# Comments shown at the top of the page (item ids). Mild ones only.
EXAMPLE_IDS = ["POOL0005", "POOL0017", "POOL0022", "POOL0002", "POOL0006", "POOL0165", "POOL0210"]

# Edit this list as the project moves on. s = "done", "part" or "todo".
CHECKLIST = [
    {"s": "done", "t": "Golden set of 150+ items", "n": "200 comments"},
    {"s": "done", "t": "Two labellers per item, agreement reported", "n": "180 of 200, kappa 0.85"},
    {"s": "part", "t": "Labelling guide (about 2 pages)", "n": "draft in data/labelling_guide.md, rules to confirm"},
    {"s": "done", "t": "Dev and test split", "n": "140 dev, 60 test"},
    {"s": "done", "t": "Harness: one command, one row per item"},
    {"s": "done", "t": "Structured output (fixed JSON schema)"},
    {"s": "done", "t": "Prompts under git with a changelog", "n": "prompts/CHANGELOG.md"},
    {"s": "done", "t": "LLM judge with fixed schema", "n": "judge_v1, grade and reason"},
    {"s": "done", "t": "Judge reliability: agreement with humans", "n": "18/39, kappa 0.15"},
    {"s": "done", "t": "Judge bias: position swap and padding", "n": "6/38 flipped, 0/39 went up"},
    {"s": "todo", "t": "Test set run (once, at the end)"},
    {"s": "done", "t": "Cost per 1k requests, today and at 100x"},
    {"s": "todo", "t": "README with setup, run and Contributions"},
    {"s": "todo", "t": "report.pdf (max 4 pages)"},
    {"s": "todo", "t": "postmortem.md"},
    {"s": "done", "t": "No API keys in the repo", "n": ".env is ignored by git"},
]



def load_judge(res):
    """Fill the judge cards from results/judge_*_summary.json (made by harness/judge.py)."""
    def read(name):
        p = res / f"judge_{name}_summary.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    a, p, v = read("agreement"), read("position"), read("verbosity")
    out = {}
    if a:
        out["agreement"] = f"{a['agree']}/{a['n']} same grade ({a['pct']}%), kappa {a['kappa']}"
    if p:
        out["position"] = f"{p['flipped']} of {p['pairs']} verdicts changed when swapped"
    if v:
        out["verbosity"] = f"grade went up for {v['up']} of {v['n']} padded answers"
    out["done"] = bool(a and p and v)
    return out


def golden():
    f = pd.read_excel(DATA_FILE, sheet_name=0)
    a = f[["student_1", "student_2", "final_label", "split"]].dropna()
    agree = int((a.student_1 == a.student_2).sum())
    out = {
        "total": int(len(a)),
        "agree": agree,
        "kappa": float(cohen_kappa_score(a.student_1, a.student_2)),
        "matrix": {
            "labels": LABELS,
            "counts": [[int(((a.student_1 == r) & (a.student_2 == c)).sum()) for c in LABELS] for r in LABELS],
        },
    }
    for sp in ["dev", "test"]:
        s = a[a.split == sp]
        out[sp] = {"n": int(len(s)), "labels": {l: int((s.final_label == l).sum()) for l in LABELS}}
    return out


def vkey(path):
    m = re.search(r"_v(\d+)", path.name)
    return (int(m.group(1)) if m else 0, path.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(BASE / "results"))
    ap.add_argument("--out", default=str(BASE / "dashboard" / "index.html"))
    args = ap.parse_args()
    res = Path(args.results)

    runs = []
    for p in sorted(res.glob("metrics_*.json"), key=vkey):
        name = p.stem.replace("metrics_", "")
        if name.endswith("_dryrun"):
            continue
        m = re.search(r"_(v\d+)_(dev|test)(_earlier_run)?$", name)
        if not m:
            continue
        runs.append({"id": name, "version": m.group(1), "split": m.group(2),
                     "note": "earlier run, prompt lost" if m.group(3) else "",
                     "metrics": json.loads(p.read_text(encoding="utf-8"))})
    runs.sort(key=lambda r: (r["split"] == "test", int(r["version"][1:])))

    examples = []
    src = [r for r in runs if r["split"] == "dev"]
    if src:
        rows = {}
        for line in (res / f"{src[-1]['id']}.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                rows[d["item_id"]] = d
        for i in EXAMPLE_IDS:
            d = rows.get(i)
            if d and d.get("predicted_label"):
                examples.append({"id": i, "text": re.sub(r"@user\s*", "", d["comment_text"]).strip(),
                                 "gold": d["gold_label"], "pred": d["predicted_label"]})

    data = {"generated": datetime.date.today().isoformat(), "model": MODEL, "price": PRICE,
            "golden": golden(), "runs": runs, "examples": examples, "judge": load_judge(res), "checklist": CHECKLIST}
    html = (BASE / "dashboard" / "template.html").read_text(encoding="utf-8")
    html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Saved {out} ({len(runs)} run(s), {len(examples)} example comments)")


if __name__ == "__main__":
    main()