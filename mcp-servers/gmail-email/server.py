"""
Gmail Email MCP Server
========================
Exposes one tool - send_email - that sends REAL email via Gmail SMTP
(smtp.gmail.com:587, STARTTLS). Unlike the mailhog-email server, mail sent
through this one actually reaches real inboxes - there is no dev safety net.

Credentials come from environment variables (GMAIL_USER, GMAIL_APP_PASSWORD),
set in .mcp.json's env block for this server - never hardcoded here.

Implements the MCP stdio JSON-RPC protocol directly (initialize, tools/list,
tools/call) using only the Python standard library - no third-party MCP SDK
dependency.
"""
import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "send_email",
        "description": (
            "Send a REAL email via Gmail SMTP. This actually delivers to the "
            "recipient's real inbox - there is no dev safety net here."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Plain-text email body"},
            },
            "required": ["to", "subject", "body"],
        },
    }
]


def send_email(to: str, subject: str, body: str) -> str:
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_USER / GMAIL_APP_PASSWORD not configured in .mcp.json env")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
        smtp.starttls()
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.sendmail(GMAIL_USER, [to], msg.as_string())

    return f"Sent real email to {to} (subject={subject!r})"


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _reply(request_id, result=None, error=None) -> None:
    message = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    _write(message)


def handle_request(request: dict) -> None:
    method = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        _reply(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "gmail-email", "version": "1.0.0"},
        })
        return

    if method == "notifications/initialized":
        return

    if method == "tools/list":
        _reply(request_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})

        if name != "send_email":
            _reply(request_id, error={"code": -32601, "message": f"Unknown tool: {name}"})
            return

        try:
            result_text = send_email(to=args["to"], subject=args["subject"], body=args["body"])
            _reply(request_id, {"content": [{"type": "text", "text": result_text}]})
        except Exception as exc:
            _reply(request_id, {
                "content": [{"type": "text", "text": f"send_email failed: {exc}"}],
                "isError": True,
            })
        return

    if request_id is not None:
        _reply(request_id, error={"code": -32601, "message": f"Unknown method: {method}"})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle_request(request)


if __name__ == "__main__":
    main()
