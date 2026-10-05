# Postmortem

What went wrong, what we learned. Numbers are from the runs in `results/`.

## 1. The first prompt was lost, so the baseline cannot be reproduced
Our first run (65/140, 46.4%) was done before the prompt was saved in git; `classifier_v1.txt` was empty in the first commit. A long prompt was pushed later, but a 5-comment check showed it uses about 1,130 tokens per comment against about 460 for the earlier run, so it is not the prompt that made the 65/140.
**Lesson:** commit the prompt before every run and record which prompt file produced each results file.

## 2. Rate limits interrupted every long run
The free Groq plan allows 8,000 tokens per minute and 200,000 per day. A full dev run costs about 150k to 210k tokens, so we got about one full run per day, and several runs stopped with HTTP 429 errors. A laptop shutdown also stopped a run.
**What helped:** the runner saves after every item and continues on re-run; a `--delay` option; `--limit` for cheap tests.
**Lesson:** budget tokens per day before planning the experiments, and run the cheap checks first.

## 3. Three comments always get an empty answer from the model
POOL0574 (robot), POOL0563 (judge) and POOL0483 (position test) return an empty answer with `json_validate_failed`, even after retries and with reasoning turned off. We did not find the cause. They stay in the counts as failures.
**Lesson:** count failures instead of dropping them, and show them in the report.

## 4. Excel and WPS destroyed the Arabic text and emojis
Saving the judge sample as CSV replaced Arabic letters and emojis with `?`. We restored the text from the UTF-8 results file with a `repair` command and moved the sheet to `.xlsx`.
**Lesson:** never round-trip UTF-8 data through CSV in a spreadsheet program.

## 5. We did not agree on the grade definition before grading
Some answers with a wrong label were first graded `good` or `partly`, although our rule says a wrong label is `bad`. We had to correct the sheet with an `enforce` command, and the human-agreement numbers only became comparable after that.
**Lesson:** write the grading rule down and check it on 5 examples before everyone grades 40.

## 6. The judge is not reliable
judge_v1 agrees with the final human grade on 18 of 39 items (46.2%, kappa 0.145). It is too lenient (`good` for 32 of 39 answers) and never says `partly`. On pairs where exactly one answer has the right label, it picked that answer in only 64.5% of calls. It has no verbosity bias in our test (0 of 39 grades went up), and 6 of 38 pairs changed verdict when the order was swapped. The reason is that the judge does not see the gold label, so a fluent wrong answer convinces it.
**What we would do next:** give the judge the gold label or a stricter rubric, and re-measure.

## 7. The dev score is optimistic
The v3 glossary was written after reading the dev comments that v2 missed. The dev gain (51.4% to 67.1%) is probably larger than the gain on new comments. The test set was kept untouched for this reason.

## 8. Labelling is subjective at the edges
The two labellers disagreed on 20 of 200 comments, mostly Humour vs Hate Speech and Positive vs Humour. With only three labels, neutral comments become `Positive` and hostile criticism becomes `Hate Speech`. A rule in v3 ("vulgar words usually mean Hate Speech") conflicts with jokes that use vulgar words (for example POOL0377, settled as Humour).
**What we would do differently:** add a fourth label (Criticism or Neutral), and test the vulgar-words rule.

## 9. Tooling problems
- Git could not merge the Excel file, so a push was rejected and a lock file blocked a pull.
- A script worked on Python 3.14 but failed on 3.10 (a backslash inside an f-string).
**Lesson:** one person edits a binary file at a time; run scripts on the oldest Python version you support.

## 10. Test set
TODO: add the test score and compare it with the dev score once the test run is done.
