# Prompt changelog

Every prompt change is listed with the score before and after. All scores are on the **dev set (140 comments)**, same model (`openai/gpt-oss-20b` on Groq, temperature 0), measured with `harness/runner.py` and `harness/scorer.py`. Failed items count as wrong. The test set (60 comments) has not been used yet.

## Classifier prompts

| Version | Correct | Accuracy | Macro-F1 | Positive found | Humour found | Hate Speech found | Failed | Cost per 1k comments |
|---|---|---|---|---|---|---|---|---|
| v1 (earlier run, prompt lost) | 65/140 | 46.4% | 0.405 | 45/59 (76.3%) | 12/40 (30.0%) | 8/41 (19.5%) | 0 | $0.09 |
| v2 | 72/140 | 51.4% | 0.485 | 41/59 (69.5%) | 20/40 (50.0%) | 11/41 (26.8%) | 1 | $0.18 |
| v3 | 94/140 | 67.1% | 0.675 | 39/59 (66.1%) | 26/40 (65.0%) | 29/41 (70.7%) | 0 | $0.23 |

Results files: `results/classifier_v1_dev_earlier_run.jsonl`, `results/classifier_v2_dev.jsonl`, `results/classifier_v3_dev.jsonl`.

### v3 (prompts/classifier_v3.txt)

**Score: 51.4% to 67.1% (72 to 94 correct, +22).**

Changes from v2:
- Told the model that the comments are Tunisian Darija, often in Latin letters with numbers (3, 7, 9), mixed with French and English.
- Added a short Darija glossary: vulgar words, religious insults, and the phrases for "they are lying" and "rich people".
- Made the Hate Speech definition explicit: vulgar and religious insults, calling people stupid or liars, and hostile or mocking attacks on groups such as rich students. There is no separate Criticism label, so hostile criticism counts as Hate Speech.
- New rules: Positive is not the default, and a comment that the model does not understand must not be treated as harmless.

Why: in v2, 21 of 41 Hate Speech comments were called Humour and 9 were called Positive. Reading them showed that most were Darija in Latin letters and the model did not know the words.

Effect:
- Hate Speech found: 11/41 to 29/41. Precision for Hate Speech: 68.8% to 82.9%.
- Humour found: 20/40 to 26/40.
- Positive found: 41/59 to 39/59 (small loss).
- Main remaining error: 18 Positive comments are called Humour.
- Cost per comment is about 31% higher because the prompt is longer (about 1,000 tokens per comment instead of about 700).

Caution: the glossary was written after reading the dev comments that v2 missed, so the dev score is probably a little optimistic. The test set has not been touched and will give the unbiased number.

Known weakness: the rule "vulgar words usually mean Hate Speech" conflicts with comments where vulgar words are used jokingly (for example POOL0377, settled as Humour by the third labeller).

### v2 (prompts/classifier_v2.txt)

**Score: 72/140 (51.4%).** Detailed guidance for the three labels and a fixed JSON output (label and short reason).

Known problems: Hate Speech found only 26.8%, and many unclear comments were called harmless. One comment (POOL0574) returned an empty answer on every attempt in this run and counts as wrong; it was answered on a later retry with v3.

### v1 (earlier run)

**Score: 65/140 (46.4%).** This was the first run. Its prompt text was not saved, so the run cannot be reproduced. It used about 230 prompt tokens per comment, so the prompt was short (roughly 800 characters). It is kept as a historical baseline only.

Note on `prompts/classifier_v1.txt`: this file was committed to git on 2026-10-05. The first commit (2026-10-01) contained an empty `classifier_v1.txt` next to the v1 results, so the prompt text was pushed later. We checked whether it is the prompt behind the 65/140 by running it on 5 dev comments: it used about 1,130 tokens per comment (5,652 tokens for 5), while the earlier run used about 460 per comment (64,253 for 140) with answers of similar length. The file therefore uses a much longer prompt than the earlier run. **Conclusion: this file is not the prompt that produced the 65/140** (it may have been edited after the run), so the earlier run cannot be reproduced from it. The file has not been run on the full dev set.

## Judge prompts

| Version | What it does | Result on the 40-item human sample |
|---|---|---|
| judge_v1 (`prompts/judge_v1.txt`) | Grades the robot's label and reason as good, partly or bad. Does not see the gold label. | Agrees with the final human grade on 18/39 items (46.2%), kappa 0.145. On the 20 rows where the robot's label is right: 13/20 (65.0%), kappa 0.136. |

Findings for judge_v1:
- Too lenient: it said `good` for 32 of 39 answers and caught only 5 of the 21 answers the humans graded `bad`. It cannot see the gold label, so a wrong label with a fluent reason convinces it.
- It never used `partly` (0 of 39 answers; humans used it 5 times).
- One item (POOL0563) always returns an empty answer from the model and was not graded (39 of 40 graded).
- The two human graders agreed on 35/40 (87.5%) overall and on 15/20 (75.0%) on the rows where the robot's label is right. Rows where the robot's label differs from the gold label are graded `bad` by rule.

Bias tests for judge_v1:
- **Verbosity:** after padding each reason with a filler sentence (13.9 to 56.9 words on average), the grade went up for 0 of 39 items, stayed the same for 34 and went down for 5. Limit of the test: 32 of 39 answers already had the top grade, so only the 7 answers graded `bad` could go up.
- **Position:** 38 pairs (the v2 and v3 answers for the same comment, where exactly one has the right label) were judged in both orders. The verdict changed for 6 of 38 pairs (15.8%). The first-shown answer was picked in 34 of 76 calls (45%), so there is no clear preference for the first position. 3 calls were ties. Two pairs are missing (POOL0483, always an empty model answer; POOL0447, rate limit).
- **Picked the answer with the right label:** 49 of 76 calls (64.5%), against 50% by chance. Without the gold label, the judge often prefers a wrong answer with a convincing reason. This is the main weakness of the judge.