# AICA Prototype (Working)

This is a minimal but working prototype of the Abnormal AI Communications Assistant (AICA) with:
- Guardrails (regex redaction for IPs, emails, hostnames, internal IDs; stack-trace line removal)
- Severity-based auto-cadence (SEV1–SEV4)
- Prompt construction per stage (initial/ongoing/resolution)
- Export templates (StatusPage snippet, Email body)
- Optional LLM generation (Standard draft) via OpenAI

## Structure
- `server/main.py` — FastAPI API (CORS enabled). Optional OpenAI integration if `OPENAI_API_KEY` is set.
- `server/requirements.txt` — Python dependencies.
- `web/index.html` — Simple UI (Stage, Severity, auto-cadence, copy-to-clipboard).
- `AICA_PRD.docx` — PRD in DOCX.
- `AICA_Presentation.pptx` — Pitch Deck for AICA.

## Quick Start (Windows PowerShell)
```powershell
# From the project root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r server\requirements.txt

# Run API (127.0.0.1:8000)
python server\main.py

# Open the UI (static file)
Start-Process .\web\index.html
```

- Fill the form and click "Generate Drafts".
- Leave "Next update" empty to auto-apply cadence from severity.
- Copy outputs via the Copy buttons.

## Optional: Enable LLM Generation (Standard Draft)
```powershell
pip install openai
$env:OPENAI_API_KEY = "<your api key>"
# Optional model & temperature
$env:OPENAI_MODEL = "gpt-4o-mini"
$env:OPENAI_TEMPERATURE = "0.3"
```
If no API key is set, the backend falls back to safe templated drafts.

## Notes
- Guardrails run on `summary` and `impact` inputs before generation.
- Exports are capped and formatted (StatusPage length ≤ 2000 chars).
- CORS is enabled to support file-based UI fetching.
