"""One function to call Groq with a fixed JSON schema (used by the judge)."""
import json
import time

import requests

API_URL = "https://api.groq.com/openai/v1/chat/completions"


def call_json(api_key, model, system_message, prompt, schema, schema_name, max_retries=6):
    """Return (parsed_json, usage). Raises RuntimeError after all retries."""
    payload = {
        "model": model,
        "temperature": 0,
        "include_reasoning": False,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error = "unknown error"
    for attempt in range(max_retries):
        try:
            r = requests.post(API_URL, headers=headers, json=payload, timeout=60)
            if r.status_code == 200:
                data = r.json()
                return json.loads(data["choices"][0]["message"]["content"]), data.get("usage", {})
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            flaky = r.status_code == 400 and "json_validate_failed" in r.text
            if r.status_code not in (429, 500, 502, 503, 504) and not flaky:
                break
            wait = 1 if flaky else float(r.headers.get("retry-after", 2 ** attempt))
        except (requests.RequestException, ValueError, KeyError, json.JSONDecodeError) as e:
            last_error = f"{type(e).__name__}: {e}"
            wait = 2 ** attempt
        time.sleep(min(wait, 60))
    raise RuntimeError(last_error)
