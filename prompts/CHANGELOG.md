# Prompt changelog

Every prompt change is listed with the score before and after. All scores are on the **dev set (140 comments)**, same model (`openai/gpt-oss-20b` on Groq, temperature 0), measured with `harness/runner.py` and `harness/scorer.py`. Failed items count as wrong. The test set (60 comments) has not been used yet.

| Version | Correct | Accuracy | Macro-F1 | Positive found | Humour found | Hate Speech found | Failed | Cost per 1k comments |
|---|---|---|---|---|---|---|---|---|
| v1 | not reproducible, see note | | | | | | | |
| v2 | 72/140 | 51.4% | 0.485 | 41/59 (69.5%) | 20/40 (50.0%) | 11/41 (26.8%) | 1 | $0.18 |
| v3 | 94/140 | 67.1% | 0.675 | 39/59 (66.1%) | 26/40 (65.0%) | 29/41 (70.7%) | 0 | $0.23 |

## v3 (prompts/classifier_v3.txt)

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

## v2 (prompts/classifier_v2.txt)

**Score: 72/140 (51.4%).** First prompt with detailed guidance for the three labels and a fixed JSON output (label and short reason).

Known problems: Hate Speech found only 26.8%, and many unclear comments were called harmless. One comment (POOL0574) returned an empty answer on every attempt and counts as wrong; it was answered on a later retry with v3.

## v1

The first prompt file was empty in the repository, so v1 cannot be reproduced. An old results file (`results/old/classifier_v1_dev.jsonl`) shows 65 of 140 correct (46.4%), but we do not know which prompt produced it, so it is not used in the table. A simple baseline prompt can be rebuilt and run if token budget allows.
