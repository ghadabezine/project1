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
