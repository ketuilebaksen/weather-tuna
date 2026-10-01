#!/usr/bin/env python3
"""
upload.py — upload work/final.mp4 to YouTube (runs in GitHub Actions).

Env: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
Usage: python3 scripts/upload.py content/current/meta.json
"""
import json, os, sys
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def yt():
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube"])
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)

def main():
    with open(sys.argv[1]) as f:
        meta = json.load(f)
    if meta.get("privacy") == "skip":
        with open("upload_result.json", "w") as f:
            json.dump({"skipped": True,
                       "note": "upload skipped (privacy=skip) — download video from Artifacts"}, f)
        print("[upload] SKIPPED by request — video only in Artifacts")
        return
    video = os.path.join(BASE, "work", "final.mp4")
    # manual thumbnail wins: drop content/current/thumbnail.jpg into the repo
    manual_thumb = os.path.join(BASE, "content", "current", "thumbnail.jpg")
    auto_yt = os.path.join(BASE, "work", "thumbnail_yt.jpg")
    auto = auto_yt if os.path.exists(auto_yt) else os.path.join(BASE, "work", "thumbnail.jpg")
    thumb = manual_thumb if os.path.exists(manual_thumb) else auto
    desc = meta["description"]
    credits_f = os.path.join(BASE, "work", "photo_credits.txt")
    if os.path.exists(credits_f):
        desc += "\n\nPhoto credits:\n" + open(credits_f).read().strip()
    body = {
        "snippet": {"title": meta["title"][:100],
                    "description": desc[:4900],
                    "tags": meta.get("tags", [])[:30],
                    "categoryId": "17",
                    "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": meta.get("privacy", "public"),
                   "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True},
    }
    # scheduled publish: upload as private with publishAt, YouTube flips it public
    pub = meta.get("publish_at")
    if pub and meta.get("privacy", "public") == "public":
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = pub
        print(f"[upload] scheduled publish at {pub}")
    # owner makes the thumbnail by hand -> upload the video without one
    skip_thumb = (os.environ.get("SKIP_THUMBNAIL", "0") == "1"
                  and not os.path.exists(manual_thumb))
    y = yt()
    media = MediaFileUpload(video, chunksize=16 * 1024 * 1024, resumable=True,
                            mimetype="video/mp4")
    try:
        req = y.videos().insert(part="snippet,status", body=body, media_body=media)
        resp, last = None, -1
        while resp is None:
            status, resp = req.next_chunk()
            if status:
                p = int(status.progress() * 100)
                if p // 10 != last:
                    print(f"[upload] {p}%", flush=True); last = p // 10
    except HttpError as e:
        if "containsSyntheticMedia" in str(e):
            del body["status"]["containsSyntheticMedia"]
            req = y.videos().insert(part="snippet,status", body=body, media_body=media)
            resp = None
            while resp is None:
                _, resp = req.next_chunk()
        else:
            raise
    vid = resp["id"]
    print(f"[upload] id={vid} privacy={resp['status']['privacyStatus']}")
    if skip_thumb:
        print("[upload] no thumbnail uploaded — owner designs it manually")
    else:
        try:
            y.thumbnails().set(videoId=vid,
                               media_body=MediaFileUpload(thumb)).execute()
            print("[upload] thumbnail set")
        except HttpError as e:
            print(f"[upload] thumbnail skipped ({e.resp.status if e.resp else '?'})")
    with open("upload_result.json", "w") as f:
        json.dump({"id": vid, "url": f"https://youtu.be/{vid}",
                   "studio": f"https://studio.youtube.com/video/{vid}/edit",
                   "privacy": resp["status"]["privacyStatus"],
                   "publish_at": meta.get("publish_at"),
                   "needs_thumbnail": skip_thumb,
                   "title": meta["title"]}, f, indent=1)
    print(f"[upload] DONE -> https://youtu.be/{vid}")

if __name__ == "__main__":
    main()
