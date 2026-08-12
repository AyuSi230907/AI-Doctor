"""Sends extracted report text to the Claude API and gets back a structured,
non-diagnostic health summary. This is decision-support only, never a
diagnosis - the prompt below enforces that framing on the model's output.
"""
import os
import json
import re
import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """You are a careful medical-report explainer inside a patient-facing app called AI Doctor.
You are NOT a doctor and must never present your output as a diagnosis or prescription.

You will be given raw text extracted from a patient's uploaded medical report (lab results,
scan notes, prescription, discharge summary, etc). The extraction may be messy (OCR noise,
broken tables) - do your best with what's there.

Respond with ONLY a single JSON object, no markdown fences, no preamble, in exactly this shape:

{
  "summary": "2-4 sentences in plain, non-alarming language explaining what the report shows.",
  "possible_conditions": [
    {"name": "string", "likelihood": "low|medium|high", "note": "one short sentence, phrased as a possibility not a diagnosis"}
  ],
  "risk_level": "low|medium|high",
  "suggestions": [
    "General, safe next steps: e.g. 'Share this report with your usual doctor', 'Recheck in follow-up appointment', dietary or lifestyle notes. Never include specific drug names, dosages, or timing."
  ],
  "red_flags": [
    "Symptoms or values that would mean the patient should seek urgent/emergency care right away. Empty array if none apply."
  ]
}

Rules:
- Use probabilistic, hedged language ("may indicate", "is sometimes associated with") - never definitive diagnostic claims.
- risk_level "high" should be reserved for values/findings that could indicate something urgent or that include any red flag.
- Never give specific medication names, dosages, or drug combinations.
- If the extracted text is too short, garbled, or doesn't look like a medical report, say so plainly in "summary", set risk_level to "low", and leave possible_conditions and red_flags empty.
- Keep the whole response concise. Output valid JSON only."""


def analyze_report(report_text):
    """Returns a dict with keys: summary, possible_conditions, risk_level,
    suggestions, red_flags, raw_response, error (error is None on success)."""

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    if not api_key:
        return _error_result("ANTHROPIC_API_KEY is not set on the server. "
                              "Add it to your .env file to enable AI analysis.")

    if not report_text or len(report_text.strip()) < 20:
        return _error_result("Could not extract enough readable text from this file. "
                              "Try a clearer scan, a text-based PDF, or a different photo.")

    user_text = report_text[:12000]  # keep prompt bounded

    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1200,
                "system": SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": f"Extracted report text:\n\n{user_text}"}
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        return _error_result(f"AI analysis request failed: {e}")

    text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    raw = "\n".join(text_blocks).strip()

    parsed = _safe_parse_json(raw)
    if parsed is None:
        return _error_result("AI response could not be parsed. Please try re-uploading.", raw_response=raw)

    return {
        "summary": parsed.get("summary", ""),
        "possible_conditions": parsed.get("possible_conditions", []),
        "risk_level": parsed.get("risk_level", "low") if parsed.get("risk_level") in ("low", "medium", "high") else "low",
        "suggestions": parsed.get("suggestions", []),
        "red_flags": parsed.get("red_flags", []),
        "raw_response": raw,
        "error": None,
    }


def _safe_parse_json(raw):
    # Strip accidental markdown fences if the model adds them anyway
    cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # try to grab the first {...} block
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return None


def _error_result(message, raw_response=""):
    return {
        "summary": "",
        "possible_conditions": [],
        "risk_level": "low",
        "suggestions": [],
        "red_flags": [],
        "raw_response": raw_response,
        "error": message,
    }
