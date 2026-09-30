import os
import json
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("GROQ_API_KEY")

MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
)

DATA_FILE = (
    BASE_DIR
    / "data"
    / "instagram_labels_split_140_dev_60_test.xlsx"
)

PROMPT_FILE = (
    BASE_DIR
    / "prompts"
    / "classifier_v2.txt"
)

RESULTS_DIR = BASE_DIR / "results"

OUTPUT_FILE = (
    RESULTS_DIR
    / "classifier_v2_dev.jsonl"
)

SHEET_NAME = "dev_set"

# None = process all 140 development comments
TEST_LIMIT = None

API_URL = (
    "https://api.groq.com/openai/v1/chat/completions"
)

ALLOWED_LABELS = {
    "Positive",
    "Humour",
    "Hate Speech"
}

# Retry settings
MAX_RETRIES = 8

# Wait between normal successful requests
DELAY_BETWEEN_REQUESTS = 3


# ============================================================
# CHECK CONFIGURATION
# ============================================================

if not API_KEY:
    raise SystemExit(
        "ERROR: GROQ_API_KEY was not found in .env"
    )

if not DATA_FILE.exists():
    raise SystemExit(
        f"ERROR: Dataset not found:\n{DATA_FILE}"
    )

if not PROMPT_FILE.exists():
    raise SystemExit(
        f"ERROR: Prompt not found:\n{PROMPT_FILE}"
    )

RESULTS_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# LOAD PROMPT
# ============================================================

with open(
    PROMPT_FILE,
    "r",
    encoding="utf-8"
) as file:

    prompt_template = file.read()


# ============================================================
# LOAD DATASET
# ============================================================

print("Loading dataset...")

df = pd.read_excel(
    DATA_FILE,
    sheet_name=SHEET_NAME
)

print(
    f"Loaded {len(df)} development comments."
)


# ============================================================
# CHECK DATASET COLUMNS
# ============================================================

required_columns = [
    "item_id",
    "comment_text",
    "final_label"
]

missing_columns = [
    column
    for column in required_columns
    if column not in df.columns
]

if missing_columns:

    raise SystemExit(
        "ERROR: Missing columns:\n"
        + "\n".join(missing_columns)
    )


# ============================================================
# LIMIT DATASET
# ============================================================

if TEST_LIMIT is not None:

    df = df.head(TEST_LIMIT)

print(
    f"Running classifier on {len(df)} comments."
)


# ============================================================
# LOAD PREVIOUS RESULTS
# ============================================================

processed_ids = set()

if OUTPUT_FILE.exists():

    with open(
        OUTPUT_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        for line in file:

            line = line.strip()

            if not line:
                continue

            try:

                result = json.loads(line)

                item_id = result.get(
                    "item_id"
                )

                predicted_label = result.get(
                    "predicted_label"
                )

                # Only count an item as processed if
                # it contains a valid classification.
                if (
                    item_id
                    and predicted_label
                    in ALLOWED_LABELS
                ):

                    processed_ids.add(
                        str(item_id)
                    )

            except json.JSONDecodeError:

                # Ignore malformed old lines
                continue


print(
    f"Already processed: {len(processed_ids)}"
)


# ============================================================
# CLASSIFY ONE COMMENT
# ============================================================

def classify_comment(comment):

    # --------------------------------------------------------
    # Build prompt
    # --------------------------------------------------------

    prompt = prompt_template.replace(
        "{{COMMENT}}",
        ""
    ).strip()

    prompt = (
        prompt
        + "\n\n"
        + "COMMENT TO CLASSIFY:\n"
        + comment
        + "\n\n"
        + "END OF COMMENT"
    )

    # --------------------------------------------------------
    # API payload
    # --------------------------------------------------------

    payload = {

        "model": MODEL,

        "messages": [

            {
                "role": "system",
                "content": (
                    "You are an Instagram comment "
                    "classification system. "
                    "Follow the classification "
                    "instructions exactly. "
                    "Return only a json object containing "
                    "the label and reason."
                )
            },

            {
                "role": "user",
                "content": prompt
            }
        ],

        "temperature": 0,

        # Do not return the model's reasoning
        "include_reasoning": False,

        # Strict structured output
        "response_format": {

            "type": "json_schema",

            "json_schema": {

                "name": (
                    "instagram_comment_classification"
                ),

                "strict": True,

                "schema": {

                    "type": "object",

                    "properties": {

                        "label": {
                            "type": "string",
                            "enum": [
                                "Positive",
                                "Humour",
                                "Hate Speech"
                            ]
                        },

                        "reason": {
                            "type": "string"
                        }
                    },

                    "required": [
                        "label",
                        "reason"
                    ],

                    "additionalProperties": False
                }
            }
        }
    }

    headers = {
        "Authorization": (
            f"Bearer {API_KEY}"
        ),
        "Content-Type": "application/json"
    }

    # --------------------------------------------------------
    # RETRY LOOP
    # --------------------------------------------------------

    for attempt in range(MAX_RETRIES):

        start_time = time.perf_counter()

        response = requests.post(
            API_URL,
            headers=headers,
            json=payload,
            timeout=90
        )

        latency_ms = (
            time.perf_counter()
            - start_time
        ) * 1000

        # ====================================================
        # SUCCESS
        # ====================================================

        if response.ok:

            data = response.json()

            break

        # ====================================================
        # 429 RATE LIMIT
        # ====================================================

        if response.status_code == 429:

            try:

                error_data = response.json()

                error = error_data.get(
                    "error",
                    {}
                )

                error_message = error.get(
                    "message",
                    ""
                )

            except Exception:

                error_message = response.text

            # 5, 10, 20, 40, 60, 60, 60, 60 seconds
            wait_seconds = min(
                5 * (2 ** attempt),
                60
            )

            print()
            print(
                "RATE LIMIT REACHED"
            )

            print(
                f"Waiting {wait_seconds} seconds "
                f"before retry "
                f"{attempt + 1}/{MAX_RETRIES}..."
            )

            print(
                f"Groq: {error_message}"
            )

            time.sleep(
                wait_seconds
            )

            continue

        # ====================================================
        # 400 JSON VALIDATION ERROR
        # ====================================================

        if response.status_code == 400:

            try:

                error_data = response.json()

                error = error_data.get(
                    "error",
                    {}
                )

                error_code = error.get(
                    "code",
                    ""
                )

                error_message = error.get(
                    "message",
                    ""
                )

                failed_generation = error.get(
                    "failed_generation",
                    ""
                )

            except Exception:

                error_code = ""
                error_message = response.text
                failed_generation = ""

            if error_code == "json_validate_failed":

                # Short retry delay because this is
                # usually an occasional generation failure.
                wait_seconds = min(
                    2 + attempt,
                    10
                )

                print()
                print(
                    "JSON VALIDATION FAILED"
                )

                print(
                    f"Retrying in {wait_seconds} seconds "
                    f"({attempt + 1}/{MAX_RETRIES})..."
                )

                if failed_generation:
                    print(
                        f"Failed generation: "
                        f"{failed_generation[:200]}"
                    )

                time.sleep(
                    wait_seconds
                )

                continue

            # Another type of 400 is a real API/request error.
            raise RuntimeError(
                f"Groq API error 400: "
                f"{error_message}"
            )

        # ====================================================
        # OTHER API ERROR
        # ====================================================

        raise RuntimeError(
            f"Groq API error "
            f"{response.status_code}: "
            f"{response.text}"
        )

    else:

        raise RuntimeError(
            "Request failed after "
            f"{MAX_RETRIES} retries."
        )

    # ========================================================
    # EXTRACT MESSAGE
    # ========================================================

    try:

        message = data[
            "choices"
        ][0][
            "message"
        ]

    except (
        KeyError,
        IndexError,
        TypeError
    ):

        raise RuntimeError(
            "Unexpected Groq response:\n"
            + json.dumps(
                data,
                indent=2,
                ensure_ascii=False
            )
        )

    content = message.get(
        "content"
    )

    if not content:

        raise RuntimeError(
            "Groq returned empty content:\n"
            + json.dumps(
                data,
                indent=2,
                ensure_ascii=False
            )
        )

    # ========================================================
    # PARSE JSON
    # ========================================================

    try:

        prediction = json.loads(
            content
        )

    except json.JSONDecodeError:

        raise RuntimeError(
            "Model returned invalid JSON:\n"
            + content
        )

    # ========================================================
    # VALIDATE PREDICTION
    # ========================================================

    predicted_label = prediction.get(
        "label"
    )

    reason = prediction.get(
        "reason"
    )

    if predicted_label not in ALLOWED_LABELS:

        raise RuntimeError(
            "Invalid label returned: "
            f"{predicted_label}"
        )

    if not isinstance(
        reason,
        str
    ):

        raise RuntimeError(
            "Invalid reason returned."
        )

    return (
        prediction,
        data,
        latency_ms
    )


# ============================================================
# MAIN CLASSIFICATION LOOP
# ============================================================

print()
print("=" * 60)
print("STARTING CLASSIFICATION")
print("=" * 60)
print()


processed_this_run = 0
skipped_this_run = 0
failed_this_run = 0


# Append mode is important:
# it preserves the 139 results you already have.

with open(
    OUTPUT_FILE,
    "a",
    encoding="utf-8"
) as output_file:

    for position, (_, row) in enumerate(
        df.iterrows(),
        start=1
    ):

        # ----------------------------------------------------
        # Get data
        # ----------------------------------------------------

        item_id = str(
            row["item_id"]
        ).strip()

        comment = str(
            row["comment_text"]
        ).strip()

        gold_label = str(
            row["final_label"]
        ).strip()

        # ----------------------------------------------------
        # Skip already completed items
        # ----------------------------------------------------

        if item_id in processed_ids:

            print(
                f"[{position}/{len(df)}] "
                f"{item_id} already processed."
            )

            skipped_this_run += 1

            continue

        # ----------------------------------------------------
        # Display item
        # ----------------------------------------------------

        print(
            f"[{position}/{len(df)}] "
            f"Processing {item_id}..."
        )

        print(
            f"Comment: {comment[:120]}"
        )

        # ----------------------------------------------------
        # CLASSIFY
        # ----------------------------------------------------

        try:

            (
                prediction,
                raw_response,
                latency_ms
            ) = classify_comment(
                comment
            )

            predicted_label = (
                prediction["label"]
            )

            reason = (
                prediction["reason"]
            )

            # ------------------------------------------------
            # Compare with gold label
            # ------------------------------------------------

            correct = (
                predicted_label
                == gold_label
            )

            # ------------------------------------------------
            # Token information
            # ------------------------------------------------

            usage = raw_response.get(
                "usage",
                {}
            )

            prompt_tokens = usage.get(
                "prompt_tokens"
            )

            completion_tokens = usage.get(
                "completion_tokens"
            )

            total_tokens = usage.get(
                "total_tokens"
            )

            # ------------------------------------------------
            # Build result
            # ------------------------------------------------

            result = {

                "item_id": item_id,

                "comment_text": comment,

                "gold_label": gold_label,

                "predicted_label": predicted_label,

                "reason": reason,

                "correct": correct,

                "latency_ms": round(
                    latency_ms,
                    2
                ),

                "model": MODEL,

                "prompt_version": "v2",

                "prompt_tokens": (
                    prompt_tokens
                ),

                "completion_tokens": (
                    completion_tokens
                ),

                "total_tokens": (
                    total_tokens
                )
            }

            # ------------------------------------------------
            # Save immediately
            # ------------------------------------------------

            output_file.write(
                json.dumps(
                    result,
                    ensure_ascii=False
                )
                + "\n"
            )

            output_file.flush()

            processed_ids.add(
                item_id
            )

            processed_this_run += 1

            # ------------------------------------------------
            # Display result
            # ------------------------------------------------

            print(
                f"Prediction: {predicted_label}"
            )

            print(
                f"Gold:       {gold_label}"
            )

            print(
                f"Correct:    {correct}"
            )

            print(
                f"Reason:     {reason}"
            )

            print(
                f"Latency:    {latency_ms:.0f} ms"
            )

            print()

            # ------------------------------------------------
            # Slow down normal requests
            # ------------------------------------------------

            time.sleep(
                DELAY_BETWEEN_REQUESTS
            )

        # ----------------------------------------------------
        # FAILURE
        # ----------------------------------------------------

        except Exception as error:

            failed_this_run += 1

            print()
            print(
                f"ERROR processing {item_id}:"
            )

            print(
                str(error)
            )

            print(
                "Skipping this item and continuing..."
            )

            print()


# ============================================================
# FINAL SUMMARY
# ============================================================

print()
print("=" * 60)
print("CLASSIFICATION FINISHED")
print("=" * 60)

print(
    f"Processed this run: "
    f"{processed_this_run}"
)

print(
    f"Skipped previously processed: "
    f"{skipped_this_run}"
)

print(
    f"Failed this run: "
    f"{failed_this_run}"
)

print(
    f"Total valid results in file: "
    f"{len(processed_ids)}"
)

print(
    "Results saved to:"
)

print(
    OUTPUT_FILE
)

print("=" * 60)