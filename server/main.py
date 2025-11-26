import os
import re
from typing import Dict, Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI()

# CORS for local file-based UI fetches
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


SEVERITY_CADENCE = {
    "SEV1": "30 minutes",
    "SEV2": "60 minutes",
    "SEV3": "2 hours",
    "SEV4": "daily or on meaningful change",
}


def default_cadence(severity: str) -> str:
    return SEVERITY_CADENCE.get(severity.upper(), "60 minutes")


def sanitize_text(text: str) -> Dict[str, Any]:
    notes = []
    redacted = text
    rules = [
        (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[redacted-ip]", "ip"),
        (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[redacted-email]", "email"),
        (r"\b[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+\b", "[redacted-host]", "hostname"),
        (r"\b(?:id|internal[-_ ]?id)[:# ]?\s*[A-Za-z0-9_-]{6,}\b", "[redacted-id]", "internal-id"),
    ]
    for pattern, repl, label in rules:
        if re.search(pattern, redacted, flags=re.IGNORECASE):
            redacted = re.sub(pattern, repl, redacted, flags=re.IGNORECASE)
            notes.append({"token": label, "action": "redacted"})

    # Remove obvious stack traces lines
    filtered_lines = []
    for line in redacted.splitlines():
        if re.search(r"Traceback|Exception|Error:| at \\/| at \\\\|Caused by:", line):
            notes.append({"token": "stack-trace-line", "action": "removed"})
            continue
        filtered_lines.append(line)
    redacted = "\n".join(filtered_lines)

    return {"text": redacted, "notes": notes}


def build_prompt(stage: str, payload: Dict[str, Any]) -> str:
    tone = (
        "You are AICA, an AI assistant generating customer-facing incident updates. "
        "Be clear, empathetic, and non-speculative. Avoid internal details, stack traces, hostnames, IPs, and employee names. "
        "Use simple language, keep within the length bound, and conclude with an explicit next-update time."
    )
    severity = payload.get("severity", "SEV3")
    next_update = payload.get("next_update") or default_cadence(severity)
    summary = payload.get("summary", "").strip()
    impact = payload.get("impact", "").strip()
    mitigation = payload.get("mitigation", "investigating").strip()

    bounds = {
        "initial": 150,
        "ongoing": 200,
        "resolution": 250,
    }.get(stage, 200)

    return (
        f"Tone & Policy: {tone}\n\n"
        f"Stage: {stage}\nSeverity: {severity}\nNext-Update: {next_update}\n"
        f"MitigationStatus: {mitigation}\nImpact: {impact}\nSummary: {summary}\n\n"
        f"Length bound: <= {bounds} words.\n"
        "Output plain text suitable for customers."
    )


def format_templates(stage: str, text: str, next_update: str) -> Dict[str, str]:
    statuspage = []
    email_lines = []

    if stage == "initial":
        statuspage.append("Service Degradation – Update")
        email_subject = "[Incident] Initial Notice"
    elif stage == "resolution":
        statuspage.append("Incident Resolved – Summary")
        email_subject = "[Incident] Resolved"
    else:
        statuspage.append("Incident Update – Progress")
        email_subject = "[Incident] Update"

    statuspage.append("")
    statuspage.append(text)
    statuspage.append("")
    statuspage.append(f"Next update: {next_update}")

    email_lines.append(email_subject)
    email_lines.append("")
    email_lines.append(text)
    email_lines.append("")
    email_lines.append(f"Next update: {next_update}")

    return {
        "statuspage": "\n".join(statuspage)[:2000],
        "email": "\n".join(email_lines),
    }


def try_llm_generate(stage: str, payload: Dict[str, Any]) -> Dict[str, str]:
    # Optional LLM integration using OpenAI, if available
    if not os.getenv("OPENAI_API_KEY"):
        return {}
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI()
        prompt = build_prompt(stage, payload)
        resp = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.3")),
            input=prompt,
        )
        # Extract text
        parts = []
        for item in resp.output:
            if getattr(item, "type", "") == "message":
                for c in getattr(item, "content", []) or []:
                    if getattr(c, "type", "") == "output_text":
                        parts.append(getattr(c, "text", ""))
        text = "\n".join([p for p in parts if p]).strip()
        if not text:
            return {}
        return {"standard": text}
    except Exception:
        return {}

@app.get("/")
def health():
    return {"status": "ok"}

@app.post("/generate")
def generate(payload: dict):
    """
    AI-style generator with optional LLM integration, rule-based guardrails,
    severity-based cadence, and export templates.
    Expected payload keys: summary, severity, impact, mitigation, next_update, stage
    """
    stage = (payload.get("stage") or "ongoing").lower()
    severity = payload.get("severity", "SEV3")
    next_update = payload.get("next_update") or default_cadence(severity)

    # Sanitize user inputs
    fields = ["summary", "impact"]
    redaction_notes = []
    for f in fields:
        redacted = sanitize_text(payload.get(f, ""))
        payload[f] = redacted["text"]
        redaction_notes.extend(redacted["notes"])

    # Attempt LLM generation when configured
    llm_out = try_llm_generate(stage, payload)
    llm_mode = "openai" if os.getenv("OPENAI_API_KEY") else "template"
    llm_used = bool(llm_out)

    def templated(style: str) -> str:
        base = (
            f"We are {payload.get('mitigation', 'investigating')} an issue impacting {payload.get('impact','unspecified scope')}. "
            f"Severity: {severity}. Next update in {next_update}. "
            f"Summary: {payload.get('summary','').strip()}"
        )
        if style == "short":
            return base
        if style == "standard":
            return base + " We will provide further details as they are verified."
        return base + " Resolution steps are underway; we will share a full summary post-resolution."

    # Build variants: prefer LLM standard if present
    drafts = {
        "short": templated("short"),
        "standard": llm_out.get("standard") if llm_out else templated("standard"),
        "detailed": templated("detailed"),
    }

    # Format exports for the standard draft
    exports = format_templates(stage, drafts["standard"], next_update)

    return JSONResponse(
        {
            "drafts": drafts,
            "exports": exports,
            "guardrails": {
                "notes": redaction_notes,
                "blocked": False,
            },
            "meta": {
                "severity": severity,
                "next_update": next_update,
                "stage": stage,
                "llm_mode": llm_mode,
                "llm_used": llm_used,
                "llm_model": os.getenv("OPENAI_MODEL") if llm_used else None,
            },
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
