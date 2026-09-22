#!/usr/bin/env python3
"""One-time interactive OAuth consent flow for the YouTube Data API v3 Desktop-app
client. Run this once to obtain a refresh token; the pipeline's actual YouTube-publish
code reads that refresh token afterward and never needs this script again (as long as
the OAuth consent screen stays in Testing mode with this account added as a test user,
or is later moved to Production).

Usage: python3 youtube_oauth_setup.py
Reads YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET from .env in this directory, and appends
YOUTUBE_REFRESH_TOKEN to the same file on success.

This is a Desktop-app OAuth client, so Google requires a loopback redirect
(http://localhost:PORT) rather than the deprecated out-of-band flow. Since this server
is headless, that redirect has to reach a browser on YOUR machine via an SSH tunnel --
see the printed instructions once this starts.
"""

import http.server
import json
import os
import urllib.parse
import urllib.request

PORT = 8090
REDIRECT_URI = f"http://localhost:{PORT}"
SCOPE = "https://www.googleapis.com/auth/youtube"
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env():
    env = {}
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v
    return env


def main():
    env = load_env()
    client_id = env["YOUTUBE_CLIENT_ID"]
    client_secret = env["YOUTUBE_CLIENT_SECRET"]

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    })

    code_holder = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in params:
                code_holder["code"] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Authorized. You can close this tab.</h1>")
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, *args):
            pass  # quiet -- avoid interleaving with the printed instructions below

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)

    print(f"1. From YOUR machine (not this server), open an SSH tunnel:")
    print(f"     ssh -L {PORT}:localhost:{PORT} <your-ssh-user>@<this-server-host>")
    print()
    print("2. In a browser on your machine, open this URL and approve access:")
    print()
    print(auth_url)
    print()
    print("   (If Google says access is blocked: this app's OAuth consent screen is in")
    print("   Testing mode -- add your Google account under Test users in Cloud Console")
    print("   first, at APIs & Services -> OAuth consent screen.)")
    print()
    print("Waiting for authorization...", flush=True)

    while "code" not in code_holder:
        server.handle_request()

    print("Got authorization code, exchanging for tokens...", flush=True)

    data = urllib.parse.urlencode({
        "code": code_holder["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req) as resp:
        tokens = json.loads(resp.read())

    if "refresh_token" not in tokens:
        print("WARNING: no refresh_token in the response -- Google only issues one the")
        print("first time an account authorizes this client. Revoke prior access at")
        print("https://myaccount.google.com/permissions and re-run this script.")
        print(tokens)
        return

    with open(ENV_PATH, "a") as f:
        f.write(f"\nYOUTUBE_REFRESH_TOKEN={tokens['refresh_token']}\n")
    os.chmod(ENV_PATH, 0o600)
    print(f"Saved YOUTUBE_REFRESH_TOKEN to {ENV_PATH}")


if __name__ == "__main__":
    main()
