#!/usr/bin/env python3
"""
oauth_exchange.py — one-time: exchange an OAuth authorization code for a
refresh token (runs in GitHub Actions where Google APIs are reachable).

Env: YT_CLIENT_ID, YT_CLIENT_SECRET, REDIRECT_URL (full localhost URL with code),
     CODE_VERIFIER (PKCE, optional)
Prints REFRESH_TOKEN=... on success (masked in logs by the workflow).
"""
import json, os, sys, urllib.parse, urllib.request

def main():
    raw = os.environ["REDIRECT_URL"].strip()
    if "code=" in raw:
        code = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)["code"][0]
    else:
        code = raw
    data = {
        "code": code,
        "client_id": os.environ["YT_CLIENT_ID"],
        "client_secret": os.environ["YT_CLIENT_SECRET"],
        "redirect_uri": "http://localhost:1/",
        "grant_type": "authorization_code",
    }
    cv = os.environ.get("CODE_VERIFIER", "").strip()
    if cv:
        data["code_verifier"] = cv
    req = urllib.request.Request("https://oauth2.googleapis.com/token",
                                 data=urllib.parse.urlencode(data).encode())
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        print("ERROR:", e.read().decode())
        sys.exit(1)
    rt = tok.get("refresh_token")
    if not rt:
        print("ERROR: no refresh_token in response:", list(tok.keys()))
        sys.exit(1)
    with open("refresh_token.txt", "w") as f:
        f.write(rt)
    print("refresh token obtained OK")

if __name__ == "__main__":
    main()
