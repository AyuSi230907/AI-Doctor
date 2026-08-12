# AI Doctor — Intelligent Healthcare Assistant

A Flask + SQLite web app where patients upload medical reports, get an AI-generated
plain-language read (via the Claude API), and automatically keep linked guardians and
hospitals in the loop — plus a one-tap Emergency button.

## What it does

- **Patient**: sign up, upload a report (PDF / image / text), get back a summary,
  possible conditions, risk level, and suggested next steps. Emergency button alerts
  all linked guardians/hospitals and gives one-tap calling.
- **Guardian**: link to a patient (by email), see their reports and get flagged
  automatically when a report comes back medium/high risk or an emergency is triggered.
- **Hospital**: same monitoring view as guardian, for continuity of care.

## Setup

```bash
cd ai_doctor
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in:
- `ANTHROPIC_API_KEY` — get one from https://console.anthropic.com/ (needed for report
  analysis to actually run; without it, uploads still work but analysis will show a
  "not configured" message instead of results).
- `SECRET_KEY` — any random string.
- `EMERGENCY_NUMBER` — the number shown on the Emergency button (defaults to 112).

Run it:
```bash
python app.py
```
Visit `http://127.0.0.1:5000`. The SQLite DB (`ai_doctor.db`) and uploads folder are
created automatically on first run.

## How the pieces fit together

- `models.py` — User (role: patient/guardian/hospital), GuardianLink, HospitalLink,
  Report, Alert.
- `extract.py` — pulls text out of uploaded PDFs (`pdfplumber`, no external binary
  needed) and images (`pytesseract`, **needs the Tesseract OCR binary installed on the
  host** — see note below).
- `ai_analysis.py` — sends extracted text to the Claude API with a system prompt that
  enforces non-diagnostic, hedged language, flags red flags, and returns structured
  JSON (summary / possible_conditions / risk_level / suggestions / red_flags).
- `app.py` — routes, auth (Flask-Login), role-based dashboards, upload pipeline, and
  the auto-alert logic (medium/high risk report → Alert rows for every linked
  guardian/hospital).

## Deploying (e.g. PythonAnywhere, matches what you're already using for Sanjeevani)

1. Upload this whole folder.
2. Create a virtualenv and `pip install -r requirements.txt`.
3. Set the same environment variables from `.env` in the host's config (or keep the
   `.env` file — `python-dotenv` loads it automatically).
4. Point the WSGI file at `app` from `app.py`.
5. **Tesseract for image OCR**: free tiers usually can't `apt-get install`. If OCR
   isn't available, PDF uploads still work fully (text extraction doesn't need
   Tesseract) — only photographed reports depend on it. You can also add a "paste
   report text" fallback field later if OCR isn't available on your host.

## Security notes before going further with this

- Passwords are hashed (`werkzeug.security`), sessions via Flask-Login — good baseline,
  but this has **no email verification, rate limiting, or HTTPS enforcement** yet.
  Add those before handling real patient data.
- Uploaded files are stored unencrypted on disk under `static/uploads/` — fine for a
  prototype, not for production health data. For real deployment, keep uploads outside
  the static/public folder and serve them through an authenticated route instead.
- The "link guardian/hospital by email" flow auto-approves — for real use you'd want
  the patient's request to need the guardian/hospital's confirmation too, not just the
  patient adding them unilaterally.

## Where this still needs you

- The AI analysis is a decision-support layer, not a diagnosis — the disclaimer is
  baked into every report view and the system prompt. Keep it that way.
- Emergency alerts currently just create DB rows + `tel:` links (opens the phone
  dialer). Real SMS/push notifications to guardians would need a provider like
  Twilio or Firebase — not wired up here.
