"""Mint a YouTube refresh token for the SitarSpheric channel.

Reuses the OAuth client (id/secret) from an existing token JSON, opens the
Google consent screen, and asks you to pick the channel. The new refresh
token is written to the output file; secret values are never printed.

Usage:
    python scripts/get_refresh_token.py \
        --client-json "D:\\E agy cli\\E api tokens\\.SitarSpheric\\token_ViolinSpheric.json" \
        --out "D:\\E agy cli\\E api tokens\\.SitarSpheric\\token_SitarSpheric.json"
"""
import argparse
import json

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/youtube"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-json", required=True,
                    help="any existing token/client JSON that carries client_id/client_secret")
    ap.add_argument("--out", required=True, help="where to write the new token JSON")
    ap.add_argument("--nickname", default="SitarSpheric")
    args = ap.parse_args()

    with open(args.client_json, "r", encoding="utf-8") as f:
        src = json.load(f)
    for scope in ("installed", "web"):
        if isinstance(src.get(scope), dict):
            src = src[scope]
            break

    config = {"installed": {
        "client_id": src["client_id"],
        "client_secret": src["client_secret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": src.get("token_uri", "https://oauth2.googleapis.com/token"),
        "redirect_uris": ["http://localhost"],
    }}

    print("Opening browser. Sign in, then pick the SitarSpheric channel.")
    flow = InstalledAppFlow.from_client_config(config, SCOPES)
    creds = flow.run_local_server(port=0, prompt="select_account consent")

    token = {
        "nickname": args.nickname,
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(token, f, indent=2)

    verify = Credentials(None, refresh_token=token["refresh_token"],
                         token_uri=token["token_uri"],
                         client_id=token["client_id"],
                         client_secret=token["client_secret"])
    yt = build("youtube", "v3", credentials=verify, cache_discovery=False)
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    for it in items:
        print("Authorized channel:", it["snippet"]["title"], "|", it["id"])
    print("Saved token for nickname:", args.nickname)


if __name__ == "__main__":
    main()
