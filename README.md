# The Grader: measuring a classifier for Tunisian Instagram comments

CS496 AI Engineering, Project 1, MedTech, Fall 2026.

**Task.** A model reads one Instagram comment (English, French, Arabic, or Tunisian Darija in Latin letters) and answers with a label (`Positive`, `Humour` or `Hate Speech`) and a short reason. The project is not about the classifier. It is about how we **measure** it: a golden set labelled by two people, a harness that scores every item, an LLM judge, and a reliability report for that judge.

## Setup (one command)

```
pip install -r requirements.txt
```

Then create a file named `.env` in the project root with one line (get a key at console.groq.com):

```
GROQ_API_KEY=your_key_here
```

The `.env` file is ignored by git. No API key is stored in this repository.

## Run (one command)

```
python harness/runner.py --prompt prompts/classifier_v3.txt --split dev --delay 8
```

It runs the prompt on all 140 dev comments and writes one row per item (input, output, score, reason) to `results/classifier_v3_dev.jsonl`. Re-running continues where it stopped and retries failed items. Add `--split test` for the 60 test comments (use the test split only for final results). `--delay 8` keeps it under Groq's free-plan limit of 8,000 tokens per minute. `--dry-run` tests the pipeline without calling the API.

Score the results (counts, per-label recall, confusion matrix, latency, cost):

```
python harness/scorer.py results/classifier_v2_dev.jsonl results/classifier_v3_dev.jsonl
```

Build the results dashboard (open `dashboard/index.html` in a browser):

```
python harness/build_dashboard.py
```

### The judge

```
python harness/judge.py grade --delay 8        # judge grades the 40-item human sample
python harness/judge.py agreement              # judge vs human grades
python harness/judge.py verbosity --delay 8    # does padding the answer raise the grade?
python harness/judge.py position --delay 8     # does swapping the order of two answers change the verdict?
```

## Repository layout

| Path | What is in it |
|---|---|
| `data/` | Golden set (`instagram_labels_split_140_dev_60_test.xlsx`: two labellers, final label, dev/test split), `labelling_guide.md`, `judge_sample.xlsx` (human grades for the judge) |
| `harness/` | `runner.py` (run a prompt), `scorer.py` (metrics), `judge.py` + `llm.py` (judge and bias tests), `schema.py` (fixed JSON schemas), `build_dashboard.py` |
| `prompts/` | Classifier prompts `classifier_v1..v3.txt`, judge prompts, `CHANGELOG.md` (every change with score before and after) |
| `results/` | Per-item results of every run and the `metrics_*.json` / `judge_*_summary.json` files |
| `dashboard/` | Results page (template and generated `index.html`) |
| `report.pdf`, `postmortem.md` | Report and postmortem |

## Results (dev set, 140 comments)

Model: `openai/gpt-oss-20b` on Groq, temperature 0. Failed items count as wrong.

| Prompt | Correct | Positive found | Humour found | Hate Speech found | Cost per 1k comments | At 100x (100k) |
|---|---|---|---|---|---|---|
| v1 (earlier run, prompt text lost) | 65/140 (46.4%) | 45/59 | 12/40 | 8/41 | $0.09 | $8.67 |
| v2 | 72/140 (51.4%) | 41/59 | 20/40 | 11/41 | $0.18 | $17.58 |
| v3 | 94/140 (67.1%) | 39/59 | 26/40 | 29/41 | $0.23 | $22.99 |

Test set (60 comments, v3, run once): **TODO: fill in after the test run** (`python harness/scorer.py results/classifier_v3_test.jsonl`).

The v3 glossary was written after reading the dev comments that v2 got wrong, so the dev score is probably a little optimistic. The test score is the unbiased one.

### Golden set

- 200 comments, 140 dev and 60 test. Two labellers labelled every comment alone: they agree on **180 of 200 (90%)**, Cohen's kappa 0.85. A third person set the final label for the 20 disagreements.
- Items dropped: none.

### Judge reliability (judge_v1, 40-item human sample)

Rows where the robot's label differs from the gold label are `bad` by rule. Humans graded the reasoning on the other rows.

| Check | Result |
|---|---|
| Judge vs final human grade | 18/39 (46.2%), kappa 0.145 |
| Same, only rows where the robot's label is right | 13/20 (65.0%), kappa 0.136 |
| Human vs human (two graders) | 35/40 (87.5%); right-label rows 15/20 (75.0%) |
| Verbosity: grade after padding the answer | up for 0 of 39, same for 34, down for 5 |
| Position: verdict changed when order swapped | 6 of 38 pairs (15.8%); first-shown answer picked in 34 of 76 calls |
| Judge picks the answer with the right label (pairwise) | 49 of 76 calls (64.5%) |

Where the judge fails: it cannot see the gold label, so a wrong label with a fluent reason convinces it (it said `good` for 32 of 39 answers and caught 5 of the 21 the humans graded `bad`), and it never used `partly`. 1 of 40 items (POOL0563) always returned an empty model answer and was not graded.

Judge cost: 40,964 tokens for the 40 grading calls.

## Known limits

- Three labels only, by choice: there is no Neutral and no Criticism label. Neutral comments land in `Positive` and hostile criticism in `Hate Speech`.
- Three comments always return an empty model answer (POOL0574, POOL0563 in the judge, POOL0483 in the position test). They stay in the counts as failures.
- The judge sample has only 40 items, so the judge numbers have wide uncertainty.

## Contributions

TODO: one entry per team member (max 4). Example format:

- **[Name]**: what you did (for example: labelled the golden set, wrote the runner, built the judge).
- **[Name]**: ...
- **[Name]**: ...
