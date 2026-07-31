"""Connect Google Workspace through a desktop loopback OAuth flow."""
from __future__ import annotations

import argparse
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from nexuss.connectors.google_workspace.oauth import (
    GoogleOAuthClient,
    build_authorization_url,
    generate_pkce_pair,
)
from nexuss.connectors.google_workspace.service import (
    GoogleWorkspaceConnectorService,
)


class _CallbackState:
    code: str | None = None
    state: str | None = None
    error: str | None = None

class _CallbackHandler(BaseHTTPRequestHandler):
    callback = _CallbackState()

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        self.callback.code = (query.get("code") or [None])[0]
        self.callback.state = (query.get("state") or [None])[0]
        self.callback.error = (query.get("error") or [None])[0]
        body = (
            b"Nexuss received the Google authorization. "
            b"You may close this browser tab."
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args

def _client_config(path: Path) -> tuple[str, str | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    record = payload.get("installed")
    if not isinstance(record, dict):
        raise SystemExit(
            "STOP: use a Google OAuth client of type Desktop app."
        )
    client_id = str(record.get("client_id", "")).strip()
    client_secret = str(record.get("client_secret") or "").strip()
    if not client_id:
        raise SystemExit("STOP: client_id is missing.")
    return client_id, client_secret or None

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--client-config",
        type=Path,
        required=True,
        help="Downloaded Google Desktop OAuth client JSON.",
    )
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    client_id, client_secret = _client_config(args.client_config)
    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    redirect_uri = (
        f"http://127.0.0.1:{server.server_port}/oauth2/callback"
    )
    expected_state = secrets.token_urlsafe(32)
    verifier, challenge = generate_pkce_pair()
    authorization_url = build_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=expected_state,
        code_challenge=challenge,
    )
    print("Opening Google authorization in the system browser.")
    print("Requested authority: Gmail, Calendar, Contacts read-only.")
    print("Credentials will be stored using Windows user-scoped DPAPI.")
    webbrowser.open(authorization_url)
    thread = threading.Thread(
        target=server.handle_request,
        daemon=True,
    )
    thread.start()
    thread.join(timeout=args.timeout)
    server.server_close()
    callback = _CallbackHandler.callback
    if thread.is_alive():
        raise SystemExit("STOP: Google authorization timed out.")
    if callback.error:
        raise SystemExit(
            f"STOP: Google authorization failed: {callback.error}"
        )
    if not callback.code or callback.state != expected_state:
        raise SystemExit(
            "STOP: Google authorization state validation failed."
        )
    token = GoogleOAuthClient().exchange_code(
        client_id=client_id,
        client_secret=client_secret,
        code=callback.code,
        code_verifier=verifier,
        redirect_uri=redirect_uri,
    )
    service = GoogleWorkspaceConnectorService.from_environment()
    profile = service.connect(
        client_id=client_id,
        client_secret=client_secret,
        token=token,
    )
    print(f"PASS: connected Google Workspace account {profile.email}")
    print("Gmail write authority added: False")
    print("Calendar write authority added: False")
    print("Contacts write authority added: False")
    print("Credentials exposed: False")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
