"""Fixed output schema for the classifier (shared by runner and, later, the judge)."""

LABELS = ["Positive", "Humour", "Hate Speech"]

CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": LABELS},
        "reason": {"type": "string"},
    },
    "required": ["label", "reason"],
    "additionalProperties": False,
}

# --- judge schemas ---
GRADES = ["good", "partly", "bad"]

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "grade": {"type": "string", "enum": GRADES},
        "reason": {"type": "string"},
    },
    "required": ["grade", "reason"],
    "additionalProperties": False,
}

PAIRWISE_SCHEMA = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "reason": {"type": "string"},
    },
    "required": ["winner", "reason"],
    "additionalProperties": False,
}
