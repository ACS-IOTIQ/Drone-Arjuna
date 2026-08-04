"""
MailHog Email MCP Server
=========================
Exposes one tool - send_email - that sends mail through DroneArjuna's local
MailHog instance. This is a DEV-ONLY tool: MailHog never delivers to a real
inbox, it just catches the message so it can be viewed at
http://localhost:8025. Nothing here touches real SMTP providers or
credentials.

Implements the MCP stdio JSON-RPC protocol directly (initialize, tools/list,
tools/call) using only the Python standard library - no third-party MCP SDK
dependency, so there is nothing here to vet or trust beyond this one file.

Talks to MailHog at MAILHOG_HOST:MAILHOG_PORT (env-overridable). Defaults to
the docker-compose service name "mailhog" so this works unmodified when run
as a container on the same compose network; falls back to localhost when
MAILHOG_HOST is set explicitly for local (non-docker) runs.
"""
import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

MAILHOG_HOST = os.environ.get("MAILHOG_HOST", "mailhog")
MAILHOG_PORT = int(os.environ.get("MAILHOG_PORT", "1025"))

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "send_email",
        "description": (
            "Send an email through the local MailHog dev SMTP catcher. "
            "Does NOT deliver to a real inbox - view sent mail at "
            "http://localhost:8025."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Plain-text email body"},
                "from_addr": {
                    "type": "string",
                    "description": "Sender address shown in the email",
                    "default": "dev@dronearjuna.local",
                },
            },
            "required": ["to", "subject", "body"],
        },
    }
]


def send_email(to: str, subject: str, body: str, from_addr: str = "dev@dronearjuna.local") -> str:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(MAILHOG_HOST, MAILHOG_PORT, timeout=5) as smtp:
        smtp.sendmail(from_addr, [to], msg.as_string())

    return f"Sent to MailHog - view at http://localhost:8025 (to={to}, subject={subject!r})"


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
            "serverInfo": {"name": "mailhog-email", "version": "1.0.0"},
        })
        return

    if method == "notifications/initialized":
        return  # notification - no response expected

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
            result_text = send_email(
                to=args["to"],
                subject=args["subject"],
                body=args["body"],
                from_addr=args.get("from_addr", "dev@dronearjuna.local"),
            )
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
