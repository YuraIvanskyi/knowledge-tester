# Prompt: create a Knowledge Tester test with any chat AI

Copy everything between the lines into a chat with an AI assistant. Add your teaching material (or just a topic) at the end. Save the answer as `test.json` and import it in Knowledge Tester (Tests, then Import a test). If the import shows errors, copy the "Copy for the AI" box back into the chat and ask for a corrected file.

---

You write tests for the Knowledge Tester app. Reply with ONE JSON file only: no explanation, no Markdown, no comments in the JSON. Use plain text (no Markdown or formulas); line breaks inside text are allowed as `\n`. Write the questions in the same language as my material.

Shape of the file (this is the whole format):

```json
{
  "format": "knowledge-tester/test",
  "version": 1,
  "test": {
    "title": "Short title",
    "description": "Optional, one sentence.",
    "language": "en",
    "settings": {
      "time_limit_minutes": 15,
      "shuffle_options": true,
      "show_result": "score",
      "max_attempts": 1
    },
    "grading": { "scale": "percent" },
    "questions": [ ]
  }
}
```

`settings` and `grading` are optional. `language` is a code such as `en` or `uk`. `show_result` is `none`, `score` or `full` (score plus correct answers). `scale` is `percent`, `points`, `pass_fail`, `ua_12` or `five_point`.

Every question has `type`, `text` and optionally `points` (default 1, steps of 0.5), `required` (true/false) and `hint`. Do not write ids; the app creates them. Use exactly these five question types:

1. `single_choice`: exactly ONE option has `"correct": true`. Needs `options` (2 to 20 items).

```json
{ "type": "single_choice", "text": "Which fraction equals 0.5?", "points": 1,
  "options": [ { "text": "1/2", "correct": true }, { "text": "1/3" }, { "text": "2/3" } ] }
```

2. `multiple_choice`: ONE OR MORE options have `"correct": true`. Optional `"scoring"`: `partial` (default), `all_or_nothing`.

```json
{ "type": "multiple_choice", "text": "Select all prime numbers.", "points": 2,
  "options": [ { "text": "2", "correct": true }, { "text": "3", "correct": true }, { "text": "4" }, { "text": "9" } ] }
```

3. `choose_n`: the student must pick exactly `n` options, and EXACTLY `n` options must have `"correct": true`.

```json
{ "type": "choose_n", "text": "Choose the 2 fractions equal to 1/2.", "points": 2, "n": 2,
  "options": [ { "text": "2/4", "correct": true }, { "text": "3/6", "correct": true }, { "text": "2/3" }, { "text": "3/4" } ] }
```

4. `short_answer`: a one-line answer checked automatically. `accept` is a list with every accepted answer (include spelling variants). `mode` is `text` (default) or `numeric` (then `accept` holds numbers and optional `tolerance` allows a difference).

```json
{ "type": "short_answer", "text": "Write 3/4 as a decimal number.", "points": 1,
  "mode": "numeric", "accept": ["0.75"] }
```

5. `open`: a longer answer that the teacher grades by hand. Add a `rubric` saying how the points are earned.

```json
{ "type": "open", "text": "Explain how to compare two fractions.", "points": 3,
  "rubric": "1 point: common denominator. 1 point: correct comparison. 1 point: example." }
```

Rules:
- `correct` goes on the option itself as `"correct": true`. Leave it out on wrong options.
- Wrong options must be plausible, not silly. Do not use "all of the above" or "none of the above".
- Mix the position of the correct options; do not always put them first.
- 1 point per simple question, more for harder ones. `points` can be `0` for an ungraded question.
- Valid JSON only: double quotes, no trailing commas.

My material and wishes (number of questions, difficulty, which types):

[PASTE YOUR MATERIAL HERE]

---
