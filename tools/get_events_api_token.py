#!/usr/bin/env python3
"""Mints a real AWS Events API bearer token via the OAuth 2.0 Authorization
Code + PKCE flow described at
https://docs.aws.amazon.com/events/latest/devguide/auth-signing-in.html

This is a one-time (well, every ~30 days) interactive sign-in helper, not a
library used by the three modules at runtime -- they all just consume
EVENTS_API_TOKEN as an environment variable. Deliberately stdlib-only
(no requests/httpx) so it runs with any system Python, no venv needed.

Usage:
    python tools/get_events_api_token.py
    # opens your browser, you sign in with AWS Builder ID, token prints below

    python tools/get_events_api_token.py --refresh <refresh_token>
    # exchanges a stored refresh token for a new access token without a browser

SECURITY NOTE: the printed access/refresh tokens are credentials. Treat them
like passwords -- do not commit them, do not paste them into chat logs you
don't control, and prefer exporting the access token into a shell
environment variable (as this script's output suggests) over writing it to
a file. The refresh token is especially sensitive: it's valid for 30 days
and is enough on its own to mint new access tokens.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import string
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

AUTHORIZE_ENDPOINT = "https://oauth.awsevents.com/oauth2/authorize"
TOKEN_ENDPOINT = "https://oauth.awsevents.com/oauth2/token"
CLIENT_ID = "7vmom55m1qstvq8i71ph127bfq"
SCOPE = "openid email events/access"
# Any of 8484-8489 is a registered callback port per the devguide; 8484 is
# used here for simplicity.
CALLBACK_PORT = 8484
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"

_UNRESERVED = string.ascii_letters + string.digits + "-._~"


def _generate_code_verifier(length: int = 64) -> str:
    """43-128 chars from the PKCE unreserved character set."""
    return "".join(secrets.choice(_UNRESERVED) for _ in range(length))


def _code_challenge_from_verifier(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class _CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


def _run_local_callback_server(expected_state: str, result: _CallbackResult) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib method name
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            params = urllib.parse.parse_qs(parsed.query)
            result.code = params.get("code", [None])[0]
            result.state = params.get("state", [None])[0]
            result.error = params.get("error", [None])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if result.error:
                self.wfile.write(f"<h1>Sign-in failed: {result.error}</h1>".encode())
            elif result.state != expected_state:
                result.error = "state_mismatch"
                self.wfile.write(b"<h1>Sign-in failed: state mismatch. Close this window.</h1>")
            else:
                self.wfile.write(b"<h1>Signed in. You can close this window and return to the terminal.</h1>")

        def log_message(self, *args) -> None:  # noqa: ANN002 - silence default stdlib logging
            pass

    server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)
    server.timeout = 120
    server.handle_request()  # blocks for exactly one request, then returns
    server.server_close()


def sign_in() -> dict:
    """Runs the full interactive PKCE flow and returns the token response."""
    verifier = _generate_code_verifier()
    challenge = _code_challenge_from_verifier(verifier)
    state = secrets.token_urlsafe(24)

    auth_params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "identity_provider": "AWSBuilderID",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    authorize_url = f"{AUTHORIZE_ENDPOINT}?{urllib.parse.urlencode(auth_params)}"

    result = _CallbackResult()
    server_thread = threading.Thread(target=_run_local_callback_server, args=(state, result), daemon=True)
    server_thread.start()

    print("Opening your browser to sign in with AWS Builder ID...")
    print(f"If it doesn't open automatically, visit:\n{authorize_url}\n")
    webbrowser.open(authorize_url)

    server_thread.join(timeout=130)
    if result.error:
        raise RuntimeError(f"Sign-in failed: {result.error}")
    if not result.code:
        raise RuntimeError("Timed out waiting for the browser sign-in callback.")

    return _exchange_code_for_tokens(result.code, verifier)


def _exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code": code,
            "code_verifier": code_verifier,
        }
    ).encode("ascii")
    return _post_token_request(body)


def refresh(refresh_token: str) -> dict:
    """Exchanges a refresh token for a new access token, no browser needed."""
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        }
    ).encode("ascii")
    return _post_token_request(body)


def _post_token_request(body: bytes) -> dict:
    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Token endpoint returned HTTP {exc.code}: {detail}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", metavar="REFRESH_TOKEN", help="Exchange a stored refresh token instead of signing in interactively.")
    args = parser.parse_args()

    tokens = refresh(args.refresh) if args.refresh else sign_in()

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in")

    print("\nSuccess. Access token expires in", expires_in, "seconds.\n")
    print("PowerShell:")
    print(f'  $env:EVENTS_API_TOKEN = "{access_token}"')
    if refresh_token:
        print("\nRefresh token (store it somewhere safe -- NOT in this repo -- valid 30 days):")
        print(f"  {refresh_token}")
        print("\nTo mint a new access token later without a browser:")
        print(f'  python tools/get_events_api_token.py --refresh "{refresh_token}"')


if __name__ == "__main__":
    main()
