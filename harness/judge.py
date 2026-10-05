"""LLM judge and its reliability tests.

Steps (from the repo root):
  python harness/judge.py sample                 # 1. makes data/judge_sample.xlsx (with dropdowns) for the humans to grade
  (the humans fill grade_1, grade_2, final_grade with good / partly / bad)
  python harness/judge.py repair                 # (if Arabic/emoji turned into '?') restores the text, keeps the grades
  python harness/judge.py prefill                # (optional) writes 'bad' where the robot's label is wrong
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
SAMPLE = BASE / "data" / "judge_sample.xlsx"
SAMPLE_CSV = BASE / "data" / "judge_sample.csv"  # old format, still readable
SAMPLE_COLS = ["item_id", "comment_text", "gold_label", "robot_label", "robot_reason", "grade_1", "grade_2", "final_grade"]
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
def write_sample(rows):
    """Write the sheet for the humans as .xlsx, with a good/partly/bad dropdown on the three grade columns."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.worksheet.datavalidation import DataValidation
    wb = Workbook()
    ws = wb.active
    ws.title = "judge_sample"
    ws.append(SAMPLE_COLS)
    for r in rows:
        ws.append([r.get(c, "") for c in SAMPLE_COLS])
    for c in ws[1]:
        c.font = Font(bold=True)
    for col, w in zip("ABCDEFGH", [11, 48, 13, 13, 70, 11, 11, 12]):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2, max_col=5):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    dv = DataValidation(type="list", formula1='"good,partly,bad"', allow_blank=True)
    dv.error = "Use good, partly or bad"
    ws.add_data_validation(dv)
    dv.add(f"F2:H{len(rows) + 1}")
    wb.save(SAMPLE)


def cmd_sample(a):
    if (SAMPLE.exists() or SAMPLE_CSV.exists()) and not a.force:
        sys.exit("A judge sample already exists (humans may have filled it). Use --force to overwrite.")
    run = [r for r in load_run(a.run_b).values() if r.get("error") is None and r.get("predicted_label")]
    wrong = [r for r in run if r["predicted_label"] != r["gold_label"]]
    right = [r for r in run if r["predicted_label"] == r["gold_label"]]
    rng = random.Random(42)
    half = a.n // 2
    pick = rng.sample(wrong, min(half, len(wrong)))
    pick += rng.sample(right, min(a.n - len(pick), len(right)))
    rng.shuffle(pick)
    SAMPLE.parent.mkdir(exist_ok=True)
    write_sample([{"item_id": r["item_id"], "comment_text": r["comment_text"], "gold_label": r["gold_label"],
                   "robot_label": r["predicted_label"], "robot_reason": r["reason"]} for r in pick])
    print(f"Saved: {SAMPLE} ({len(pick)} items: {sum(r in wrong for r in pick)} with a wrong label, "
          f"{sum(r in right for r in pick)} with a right label)")
    print("Humans: fill grade_1 and grade_2 alone (good / partly / bad). A third person fills final_grade where they differ.")


def cmd_convert(a):
    """Turn an existing data/judge_sample.csv (with grades already in it) into data/judge_sample.xlsx."""
    if not SAMPLE_CSV.exists():
        sys.exit("No data/judge_sample.csv to convert.")
    if SAMPLE.exists() and not a.force:
        sys.exit("data/judge_sample.xlsx already exists. Use --force to overwrite it.")
    with open(SAMPLE_CSV, newline="", encoding="utf-8-sig") as f:
        sample = f.read()
    import io
    first = sample.splitlines()[0] if sample else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(sample), delimiter=delim))
    write_sample(rows)
    print(f"Saved: {SAMPLE} ({len(rows)} rows, grades kept)")


def read_sample():
    """Rows of the human sheet: from .xlsx if it exists, else from the old .csv."""
    if SAMPLE.exists():
        from openpyxl import load_workbook
        ws = load_workbook(SAMPLE, read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        head = [str(h).strip() if h is not None else "" for h in next(it)]
        return [{h: ("" if v is None else str(v)) for h, v in zip(head, row)} for row in it if row and row[0]]
    if SAMPLE_CSV.exists():
        with open(SAMPLE_CSV, newline="", encoding="utf-8-sig") as f:
            first = f.readline()
            f.seek(0)
            return list(csv.DictReader(f, delimiter=";" if first.count(";") > first.count(",") else ","))
    sys.exit("Run 'sample' first.")


def cmd_prefill(a):
    """Write 'bad' in the grade columns of every row where the robot's label differs from the gold label.
    By our labelling guide a wrong label is always 'bad', so this saves the humans 20 rows. Empty cells only."""
    from openpyxl import load_workbook
    if not SAMPLE.exists():
        sys.exit("data/judge_sample.xlsx not found. Run 'convert' or 'sample' first.")
    wb = load_workbook(SAMPLE)
    ws = wb.active
    head = {str(c.value).strip(): c.column for c in ws[1] if c.value}
    cols = ["grade_1", "grade_2"] if a.column == "both" else [a.column]
    filled = 0
    for row in range(2, ws.max_row + 1):
        gold, robot = ws.cell(row, head["gold_label"]).value, ws.cell(row, head["robot_label"]).value
        if gold is None or gold == robot:
            continue
        for c in cols:
            cell = ws.cell(row, head[c])
            if cell.value in (None, ""):
                cell.value = "bad"
                filled += 1
    wb.save(SAMPLE)
    print(f"Wrote 'bad' in {filled} empty cell(s) of {', '.join(cols)} where the robot's label is wrong.")
    print("The humans only need to grade the rows where the robot's label is right.")


def cmd_repair(a):
    """Restore the text columns of data/judge_sample.xlsx from the results file (item_id match).
    Use it when WPS/Excel replaced Arabic letters and emojis by '?'. The grades are not touched."""
    from openpyxl import load_workbook
    from openpyxl.worksheet.datavalidation import DataValidation
    if not SAMPLE.exists():
        sys.exit("data/judge_sample.xlsx not found.")
    run = load_run(a.run_b)
    wb = load_workbook(SAMPLE)
    ws = wb.active
    head = {str(c.value).strip(): c.column for c in ws[1] if c.value}
    fixed = missing = 0
    for row in range(2, ws.max_row + 1):
        item = ws.cell(row, head["item_id"]).value
        if not item:
            continue
        src = run.get(str(item).strip())
        if not src:
            missing += 1
            continue
        for col, key in [("comment_text", "comment_text"), ("gold_label", "gold_label"),
                         ("robot_label", "predicted_label"), ("robot_reason", "reason")]:
            if col in head and ws.cell(row, head[col]).value != src[key]:
                ws.cell(row, head[col]).value = src[key]
                fixed += 1
    if not ws.data_validations.dataValidation:  # put the dropdown back if the save removed it
        dv = DataValidation(type="list", formula1='"good,partly,bad"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"F2:H{ws.max_row}")
    wb.save(SAMPLE)
    print(f"Restored {fixed} text cell(s) from {Path(a.run_b).name}. Items not found in the results file: {missing}.")


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
    hum, jud, skipped, right_label = [], [], 0, []
    for r in sample:
        g1, g2, fin = norm_grade(r["grade_1"]), norm_grade(r["grade_2"]), norm_grade(r["final_grade"])
        # final_grade wins; else both graders agree; else a single grader's grade (if only one column is filled)
        final = fin or (g1 if g1 and g1 == g2 else None) or (g1 if g1 and not g2 else None) or (g2 if g2 and not g1 else None)
        if not final or r["item_id"] not in judged:
            skipped += 1
            continue
        hum.append(final)
        jud.append(judged[r["item_id"]]["grade"])
        right_label.append(r["gold_label"] == r["robot_label"])
    if not hum:
        sys.exit("No usable pairs yet. Needs human grades in data/judge_sample.xlsx AND the judge's grades "
                 "(run 'grade' first). Humans filled: "
                 f"{sum(1 for r in sample if norm_grade(r['final_grade']) or norm_grade(r['grade_1']))} rows; "
                 f"judge graded: {len(judged)} rows.")
    agree = sum(h == j for h, j in zip(hum, jud))
    kappa = cohen_kappa_score(hum, jud) if len(set(hum + jud)) > 1 else 1.0
    conf = {h: {j: sum(1 for x, y in zip(hum, jud) if x == h and y == j) for j in GRADES} for h in GRADES}
    out = {"n": len(hum), "agree": agree, "pct": pct(agree, len(hum)), "kappa": round(kappa, 3),
           "skipped": skipped, "confusion_human_rows_judge_cols": conf}
    # Rows with a wrong robot label are 'bad' by the labelling guide, so they are easy.
    # The real test of the judge is the rows where the robot's label is right (good / partly / bad).
    sub = [(h, j) for h, j, rl in zip(hum, jud, right_label) if rl]
    if sub:
        sa = sum(h == j for h, j in sub)
        hs, js = [h for h, _ in sub], [j for _, j in sub]
        sk = cohen_kappa_score(hs, js) if len(set(hs + js)) > 1 else 1.0
        out["right_label_rows"] = {"n": len(sub), "agree": sa, "pct": pct(sa, len(sub)), "kappa": round(sk, 3)}
    pairs = [(norm_grade(r["grade_1"]), norm_grade(r["grade_2"]), r["gold_label"] == r["robot_label"]) for r in sample]
    pairs = [p for p in pairs if p[0] and p[1]]
    if pairs:
        ha = sum(x == y for x, y, _ in pairs)
        out["humans_vs_humans"] = {"n": len(pairs), "agree": ha, "pct": pct(ha, len(pairs))}
        rp = [(x, y) for x, y, rl in pairs if rl]
        if rp:
            out["humans_vs_humans_right_label_rows"] = {"n": len(rp), "agree": sum(x == y for x, y in rp),
                                                        "pct": pct(sum(x == y for x, y in rp), len(rp))}
    print(f"Judge vs humans: {agree}/{len(hum)} same grade ({out['pct']}%), kappa {out['kappa']}. Skipped: {skipped}")
    corner = "human \\ judge"
    print(f"{corner:<16}" + "".join(f"{g:>8}" for g in GRADES))
    for h in GRADES:
        print(f"{h:<16}" + "".join(f"{conf[h][g]:>8}" for g in GRADES))
    if "right_label_rows" in out:
        r = out["right_label_rows"]
        print(f"Only rows where the robot's label is right: {r['agree']}/{r['n']} same grade ({r['pct']}%), kappa {r['kappa']}")
    if "humans_vs_humans" in out:
        print(f"Humans vs humans: {out['humans_vs_humans']['agree']}/{out['humans_vs_humans']['n']} ({out['humans_vs_humans']['pct']}%)")
    if "humans_vs_humans_right_label_rows" in out:
        r = out["humans_vs_humans_right_label_rows"]
        print(f"Humans vs humans, right-label rows only: {r['agree']}/{r['n']} ({r['pct']}%)")
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
    for name, fn in [("sample", cmd_sample), ("convert", cmd_convert), ("prefill", cmd_prefill), ("repair", cmd_repair), ("grade", cmd_grade), ("agreement", cmd_agreement),
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
        p.add_argument("--column", default="both", choices=["both", "grade_1", "grade_2"], help="for prefill")
    args = ap.parse_args()
    RES.mkdir(exist_ok=True)
    args.fn(args)


if __name__ == "__main__":
    main()