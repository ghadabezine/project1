# Labelling guide

Task: give each Instagram comment exactly one label: **Positive**, **Humour** or **Hate Speech**.
The comments come from a real Instagram account. They are written in English, French, Arabic script and Tunisian Darija in Latin letters (3 = ع, 7 = ح, 9 = ق), often mixed, often with emojis.

## How the labels were made

- Two labellers (`student_1`, `student_2`) labelled every comment alone, without seeing each other's label.
- They agreed on 180 of 200 comments (90%, Cohen's kappa 0.85).
- For the 20 comments where they differed, a **third person** chose the final label (`final_label`). In all 20 cases the final label is one of the two original labels.
- Always label the comment alone, from its words and emojis. Do not use the video or the post, and do not guess what the video showed.

## The three labels

### Positive
The comment shows appreciation, affection, thanks, support, agreement or admiration. Short neutral reactions and questions with no joke and no hostility also go here, because there is no Neutral label.

Examples: `Magnifique 😍` · `@user loveyou ❤️` · `Thank you 😌` · `First` · `What does this song mean?` · `So relatable 😔😔🤣🤣` (agreeing with the post) · `10/10 ragebait 👏` (praise)

### Humour
The main purpose is to be funny or playful: jokes, teasing, laughter, exaggeration, sarcasm that attacks nobody.

Examples: `hhhhhhhhhhhh` · `@user GO TO BED 🤣🤣` · `Let him be, it's the dragon of dirge 😭😭` · `Oh the locals are about to be ragebaited so bad 😭😭😭` · `@user I gave u my highlighter 😩` (playful complaint)

### Hate Speech
The main purpose is to insult, degrade or attack a person or group. This includes:
- vulgar insults and sexual insults, insults to someone's mother or family
- religious insults (calling someone ungodly)
- calling people stupid, liars or fake
- hostile or mocking attacks on a group, for example rich students, people showing off cars or money, people called materialistic

Examples: `Kolha tihchi fih` (they are all lying) · `Kroz ta3 zebi` · `Ri99 il bered` · `A Range Rover for a student????????)?` · `no bc why is it so materialistic?????? my friends are awesome`

There is no separate Criticism label. Hostile or mocking criticism of a person or group is Hate Speech, even without a classic insult.

## Darija words you will meet

| Word | Meaning |
|---|---|
| zeb, zby, zab, azebi | dick (vulgar insult) |
| nik omk / nik rohy | f*** your mother / f*** me (strong profanity) |
| kroz | vulgar word; in these comments it often means "rich people" |
| kofar | ungodly (insult) |
| ri99, tracha9, ta7an | vulgar insults |
| tihchi fih, ta7chi fih, يحشيو فيه | they are lying |
| خنانة | snot (insult) |

## Decision rules

1. Ask what the comment is for: to praise, to joke, or to attack. Pick that label.
2. If it attacks a person or group, it is Hate Speech. If it only teases and everyone could laugh, it is Humour.
3. Vulgar words are a strong sign of Hate Speech, but not enough alone. If the tone is clearly joking (laughing emojis, joking about a price or an exchange with friends), the final label can be Humour. Example: `Ha zebi 1200€??? ... 😂😂😂` was settled as Humour.
4. Comments about wealth (cars, expensive clothes): resentful or mocking about a group is Hate Speech (`A Range Rover for a student????`); a light joke about the price is Humour (`لبسة غالية من الصباغين 😂`).
5. Emojis do not decide the label. 😂 can appear on Humour, Positive and Hate Speech comments.
6. "So relatable", "me too", "same" are agreement, so Positive.
7. @mentions and tags do not decide the label. Label the message around them.
8. Do not label a comment Humour just because you do not understand it. If you cannot understand a word, ask someone who speaks Darija.
9. Remaining hard cases: Humour vs Hate Speech (11 of the 20 disagreements) and Positive vs Humour (7 of 20). When unsure between these, apply rule 2.

## What a good robot answer looks like

The system returns a label and a one-sentence reason. This is how the judge grades the reason.

- **Good:** the label is right and the reason names what in the comment shows it. Example: "Insults a group with a vulgar word and mocks them."
- **Partly good:** the label is right but the reason is vague or only repeats the label.
- **Bad:** the label is wrong; or the reason invents context that is not in the comment; or the reason says the meaning is unclear and then picks a harmless label anyway.

## Known limits

- Three labels only: no Neutral and no Criticism label, so neutral comments land in Positive and hostile criticism in Hate Speech.
- The third person's decisions on the 20 hard comments are the only tie-break record; rules 3, 4 and 9 above summarise them.
