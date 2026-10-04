"""LLM judge and its reliability tests.

Steps (from the repo root):
  python harness/judge.py sample                 # 1. makes data/judge_sample.csv for the humans to grade
  (the humans fill grade_1, grade_2, final_grade with good / partly / bad)
  python harness/judge.py grade --delay 8        # 2. the judge grades the same items
  python harness/judge.py agreement              # 3. judge vs humans
  python harness/judge.py position --delay 8     # 4. position bias: swap the order of two answers
  python harness/judge.py verbosity --delay 8    # 5. verbosity bias: pad the answer, does the grade go up?

Add --dry-run to any step to test without the API (fake grades).
Every step saves a results/judge_*.jsonl file (one row per call) and a results/judge_*_summary.json.
"""
import argparse
import csv
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from sklearn.metrics import cohen_kappa_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import call_json  # noqa: E402
from schema import GRADES, JUDGE_SCHEMA, PAIRWISE_SCHEMA  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
RES = BASE / "results"
SAMPLE = BASE / "data" / "judge_sample.csv"
SYSTEM = "You are a careful, fair grader. Return only a json object."
# Padding adds length but no information. Used for the verbosity test.
FILLER = ("To explain this in more detail: reading the comment carefully and considering its overall tone, "
          "its wording and its emojis together, and weighing the different ways it could be understood, "
          "this is the reading that seems most appropriate overall, taking everything into account.")
SCORE = {"bad": 0, "partly": 1, "good": 2}


def prompt_text(name, **fields):
    t = (BASE / "prompts" / name).read_text(encoding="utf-8")
    for k, v in fields.items():
        t = t.replace("{{" + k + "}}", str(v))
    return t


def load_run(path):
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["item_id"]] = r
    return rows


def load_jsonl(path):
    """item_id -> row, only successful rows. Empty if the file does not exist yet."""
    if not Path(path).exists():
        return {}
    rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    return {r["item_id"]: r for r in rows if r.get("error") is None}


def pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def norm_grade(x):
    x = str(x).strip().lower()
    return {"g": "good", "p": "partly", "b": "bad"}.get(x, x if x in GRADES else None)


class Judge:
    def __init__(self, args):
        load_dotenv(BASE / ".env")
        self.dry = args.dry_run
        self.key = os.getenv("GROQ_API_KEY")
        self.model = args.model or os.getenv("JUDGE_MODEL") or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        if not self.key and not self.dry:
            sys.exit("ERROR: GROQ_API_KEY not found in .env (or use --dry-run)")

    def ask(self, prompt, schema, name):
        if self.dry:  # fake but repeatable answer
            h = int(hashlib.md5(prompt.encode()).hexdigest(), 16)
            if "winner" in schema["properties"]:
                return {"winner": ["A", "B", "tie"][h % 3], "reason": "dry run"}, {}
            return {"grade": GRADES[h % 3], "reason": "dry run"}, {}
        out, usage = call_json(self.key, self.model, SYSTEM, prompt, schema, name)
        if "winner" in schema["properties"] and out.get("winner") not in ("A", "B", "tie"):
            raise RuntimeError(f"bad winner: {out}")
        if "grade" in schema["properties"] and out.get("grade") not in GRADES:
            raise RuntimeError(f"bad grade: {out}")
        return out, usage


def run_batch(out, jobs, delay, dry):
    """jobs = [(key, function)]. One row per job, saved after each; re-running retries only failures."""
    done = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["key"]] = r
    rows = []
    save = lambda: out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    out.parent.mkdir(exist_ok=True)
    for i, (key, fn) in enumerate(jobs, 1):
        prev = done.get(key)
        if prev and prev.get("error") is None:
            rows.append(prev)
            continue
        row = {"key": key, "error": None}
        t0 = time.perf_counter()
        try:
            row.update(fn())
        except RuntimeError as e:
            row["error"] = str(e)
            print(f"  [{i}] {key} FAILED: {e}")
        row["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        rows.append(row)
        save()
        if not dry:
            time.sleep(delay)
    save()
    print(f"Saved: {out}")
    return rows


def write_summary(name, data):
    p = RES / f"judge_{name}_summary.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved: {p}")


# ---------------------------------------------------------------- 1. sample
def cmd_sample(a):
    if SAMPLE.exists() and not a.force:
        sys.exit(f"{SAMPLE} already exists (humans may have filled it). Use --force to overwrite.")
    run = [r for r in load_run(a.run_b).values() if r.get("error") is None and r.get("predicted_label")]
    wrong = [r for r in run if r["predicted_label"] != r["gold_label"]]
    right = [r for r in run if r["predicted_label"] == r["gold_label"]]
    rng = random.Random(42)
    half = a.n // 2
    pick = rng.sample(wrong, min(half, len(wrong)))
    pick += rng.sample(right, min(a.n - len(pick), len(right)))
    rng.shuffle(pick)
    SAMPLE.parent.mkdir(exist_ok=True)
    with open(SAMPLE, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "comment_text", "gold_label", "robot_label", "robot_reason",
                    "grade_1", "grade_2", "final_grade"])
        for r in pick:
            w.writerow([r["item_id"], r["comment_text"], r["gold_label"], r["predicted_label"], r["reason"], "", "", ""])
    print(f"Saved: {SAMPLE} ({len(pick)} items: {sum(r in wrong for r in pick)} with a wrong label, "
          f"{sum(r in right for r in pick)} with a right label)")
    print("Humans: fill grade_1 and grade_2 alone (good / partly / bad). A third person fills final_grade where they differ.")


def read_sample():
    if not SAMPLE.exists():
        sys.exit("Run 'sample' first.")
    with open(SAMPLE, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- 2. grade
def cmd_grade(a):
    j = Judge(a)
    jobs = []
    for r in read_sample():
        def fn(r=r):
            p = prompt_text("judge_v1.txt", COMMENT=r["comment_text"], LABEL=r["robot_label"], REASON=r["robot_reason"])
            out, u = j.ask(p, JUDGE_SCHEMA, "judge_grade")
            return {"item_id": r["item_id"], "grade": out["grade"], "judge_reason": out["reason"],
                    "total_tokens": u.get("total_tokens"), "model": j.model}
        jobs.append((r["item_id"], fn))
    rows = run_batch(RES / "judge_grades.jsonl", jobs, a.delay, a.dry_run)
    ok = [r for r in rows if r["error"] is None]
    print(f"Graded {len(ok)} of {len(rows)} items. Count: " +
          ", ".join(f"{g} {sum(r['grade'] == g for r in ok)}" for g in GRADES))


# ---------------------------------------------------------------- 3. agreement
def cmd_agreement(a):
    sample = read_sample()
    judged = load_jsonl(RES / "judge_grades.jsonl")
    hum, jud, skipped = [], [], 0
    for r in sample:
        g1, g2, fin = norm_grade(r["grade_1"]), norm_grade(r["grade_2"]), norm_grade(r["final_grade"])
        final = fin or (g1 if g1 and g1 == g2 else None)
        if not final or r["item_id"] not in judged:
            skipped += 1
            continue
        hum.append(final)
        jud.append(judged[r["item_id"]]["grade"])
    if not hum:
        sys.exit("No human grades found yet. Fill data/judge_sample.csv and run 'grade' first.")
    agree = sum(h == j for h, j in zip(hum, jud))
    kappa = cohen_kappa_score(hum, jud) if len(set(hum + jud)) > 1 else 1.0
    conf = {h: {j: sum(1 for x, y in zip(hum, jud) if x == h and y == j) for j in GRADES} for h in GRADES}
    out = {"n": len(hum), "agree": agree, "pct": pct(agree, len(hum)), "kappa": round(kappa, 3),
           "skipped": skipped, "confusion_human_rows_judge_cols": conf}
    pairs = [(norm_grade(r["grade_1"]), norm_grade(r["grade_2"])) for r in sample]
    pairs = [(x, y) for x, y in pairs if x and y]
    if pairs:
        ha = sum(x == y for x, y in pairs)
        out["humans_vs_humans"] = {"n": len(pairs), "agree": ha, "pct": pct(ha, len(pairs))}
    print(f"Judge vs humans: {agree}/{len(hum)} same grade ({out['pct']}%), kappa {out['kappa']}. Skipped: {skipped}")
    print(f"{'human \\ judge':<16}" + "".join(f"{g:>8}" for g in GRADES))
    for h in GRADES:
        print(f"{h:<16}" + "".join(f"{conf[h][g]:>8}" for g in GRADES))
    if "humans_vs_humans" in out:
        print(f"Humans vs humans: {out['humans_vs_humans']['agree']}/{out['humans_vs_humans']['n']} ({out['humans_vs_humans']['pct']}%)")
    write_summary("agreement", out)


# ---------------------------------------------------------------- 4. position bias
def cmd_position(a):
    j = Judge(a)
    ra, rb = load_run(a.run_a), load_run(a.run_b)
    pairs = []
    for i in sorted(set(ra) & set(rb)):
        x, y = ra[i], rb[i]
        if x.get("error") or y.get("error") or not x.get("predicted_label") or not y.get("predicted_label"):
            continue
        # keep pairs with a clear winner: exactly one of the two labels is right
        if (x["predicted_label"] == x["gold_label"]) != (y["predicted_label"] == y["gold_label"]):
            pairs.append(i)
    pairs = random.Random(42).sample(pairs, min(a.n, len(pairs)))
    jobs = []
    for i in pairs:
        for order in ("AB", "BA"):
            first, second = (ra[i], rb[i]) if order == "AB" else (rb[i], ra[i])
            def fn(i=i, order=order, first=first, second=second):
                p = prompt_text("judge_pairwise_v1.txt", COMMENT=ra[i]["comment_text"],
                                LABEL_A=first["predicted_label"], REASON_A=first["reason"],
                                LABEL_B=second["predicted_label"], REASON_B=second["reason"])
                out, u = j.ask(p, PAIRWISE_SCHEMA, "judge_pair")
                w = out["winner"]
                who = "tie" if w == "tie" else (("a" if w == "A" else "b") if order == "AB" else ("b" if w == "A" else "a"))
                return {"item_id": i, "order": order, "winner_position": w, "winner_run": who,
                        "judge_reason": out["reason"], "total_tokens": u.get("total_tokens")}
            jobs.append((f"{i}|{order}", fn))
    rows = run_batch(RES / "judge_position.jsonl", jobs, a.delay, a.dry_run)
    by = {}
    for r in rows:
        if r["error"] is None:
            by.setdefault(r["item_id"], {})[r["order"]] = r
    full = {i: d for i, d in by.items() if len(d) == 2}
    consistent = sum(d["AB"]["winner_run"] == d["BA"]["winner_run"] for d in full.values())
    first_pos = sum(r["winner_position"] == "A" for d in full.values() for r in d.values())
    ties = sum(r["winner_position"] == "tie" for d in full.values() for r in d.values())
    right = 0
    for i, d in full.items():
        correct_run = "a" if ra[i]["predicted_label"] == ra[i]["gold_label"] else "b"
        right += sum(r["winner_run"] == correct_run for r in d.values())
    n = len(full)
    out = {"pairs": n, "consistent": consistent, "flipped": n - consistent, "pct_flipped": pct(n - consistent, n),
           "picked_first_position": first_pos, "ties": ties, "calls": 2 * n,
           "picked_right_label_answer": right}
    print(f"\nPosition bias: {n - consistent} of {n} pairs changed verdict when the order was swapped ({out['pct_flipped']}%).")
    print(f"Picked the first-shown answer in {first_pos} of {2 * n} calls (no bias would be about half of the non-tie calls). Ties: {ties}.")
    print(f"Picked the answer with the right label: {right} of {2 * n} calls.")
    write_summary("position", out)


# ---------------------------------------------------------------- 5. verbosity bias
def cmd_verbosity(a):
    j = Judge(a)
    grades = load_jsonl(RES / "judge_grades.jsonl")
    if not grades:
        sys.exit("Run 'grade' first: the padded answers are compared with the original grades.")
    jobs = []
    for r in read_sample():
        if r["item_id"] not in grades:
            continue
        def fn(r=r):
            padded = r["robot_reason"].rstrip() + " " + FILLER
            p = prompt_text("judge_v1.txt", COMMENT=r["comment_text"], LABEL=r["robot_label"], REASON=padded)
            out, u = j.ask(p, JUDGE_SCHEMA, "judge_grade")
            return {"item_id": r["item_id"], "grade_padded": out["grade"], "judge_reason": out["reason"],
                    "words_before": len(r["robot_reason"].split()), "words_after": len(padded.split()),
                    "total_tokens": u.get("total_tokens")}
        jobs.append((r["item_id"], fn))
    rows = [r for r in run_batch(RES / "judge_verbosity.jsonl", jobs, a.delay, a.dry_run) if r["error"] is None]
    up = same = down = 0
    for r in rows:
        d = SCORE[r["grade_padded"]] - SCORE[grades[r["item_id"]]["grade"]]
        up += d > 0
        same += d == 0
        down += d < 0
    n = len(rows)
    out = {"n": n, "up": up, "same": same, "down": down, "pct_up": pct(up, n),
           "mean_words_before": round(sum(r["words_before"] for r in rows) / n, 1) if n else 0,
           "mean_words_after": round(sum(r["words_after"] for r in rows) / n, 1) if n else 0}
    print(f"\nVerbosity bias: after padding the answers ({out['mean_words_before']} to {out['mean_words_after']} words on average), "
          f"the grade went up for {up} of {n} items, stayed the same for {same}, went down for {down}.")
    write_summary("verbosity", out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("sample", cmd_sample), ("grade", cmd_grade), ("agreement", cmd_agreement),
                     ("position", cmd_position), ("verbosity", cmd_verbosity)]:
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--run-a", default=str(RES / "classifier_v2_dev.jsonl"))
        p.add_argument("--run-b", default=str(RES / "classifier_v3_dev.jsonl"))
        p.add_argument("--n", type=int, default=40)
        p.add_argument("--model", default=None, help="judge model (default: $JUDGE_MODEL, then $GROQ_MODEL)")
        p.add_argument("--delay", type=float, default=8.0)
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--force", action="store_true")
    args = ap.parse_args()
    RES.mkdir(exist_ok=True)
    args.fn(args)


if __name__ == "__main__":
    main()
