#!/usr/bin/env python3
"""Upload locally generated images to TikTok Seller Center Media Library.

Required .env variables (get from TikTok Open Platform):
  TIKTOK_APP_KEY       — App Key from your TikTok developer app
  TIKTOK_APP_SECRET    — App Secret from your TikTok developer app
  TIKTOK_ACCESS_TOKEN  — Shop access token (from Seller Center → My Apps → Access Token)

API used: TikTok Shop Open Platform v1
  POST /api/products/img/upload
  Docs: https://partner.tiktokshop.com/docv2/page/product-api
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TIKTOK_API_BASE = "https://open-api.tiktokglobal.com"
UPLOAD_PATH = "/api/products/img/upload"


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def check_credentials() -> bool:
    load_env_file()
    return bool(
        os.environ.get("TIKTOK_APP_KEY")
        and os.environ.get("TIKTOK_APP_SECRET")
        and os.environ.get("TIKTOK_ACCESS_TOKEN")
    )


def _sign(secret: str, params: dict[str, str]) -> str:
    """Compute TikTok API signature (MD5, uppercase)."""
    pairs = sorted((k, v) for k, v in params.items() if k not in ("sign", "access_token"))
    base = secret + "".join(f"{k}{v}" for k, v in pairs) + secret
    return hashlib.md5(base.encode("utf-8")).hexdigest().upper()


def _auth_params() -> dict[str, str]:
    app_key = os.environ.get("TIKTOK_APP_KEY", "")
    app_secret = os.environ.get("TIKTOK_APP_SECRET", "")
    access_token = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
    params: dict[str, str] = {
        "app_key": app_key,
        "access_token": access_token,
        "timestamp": str(int(time.time())),
        "sign_method": "md5",
    }
    params["sign"] = _sign(app_secret, params)
    return params


def upload_image_file(file_path: Path) -> str:
    """Upload a local image file to TikTok Media Library.

    Returns the TikTok-hosted CDN URL on success.
    Raises RuntimeError on API failure.
    """
    load_env_file()
    params = _auth_params()
    query = "&".join(f"{k}={v}" for k, v in params.items())
    endpoint = f"{TIKTOK_API_BASE}{UPLOAD_PATH}?{query}"

    image_bytes = file_path.read_bytes()
    ext = file_path.suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(
        ext.lstrip("."), "image/png"
    )

    boundary = "TikTokUploadBoundary7823"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="img_data"; filename="{file_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + image_bytes + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"TikTok API HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"TikTok API network error: {exc}") from exc

    if data.get("code") != 0:
        raise RuntimeError(f"TikTok upload failed — {data.get('msg')} (code {data.get('code')})")

    tiktok_url: str = data.get("data", {}).get("url", "")
    if not tiktok_url:
        raise RuntimeError(f"TikTok upload returned no URL: {data}")
    return tiktok_url


def upload_listing_images(listing_item: dict[str, Any]) -> dict[str, str]:
    """Upload all local generated images for one listing to TikTok.

    Skips slots that already have a non-local (public) URL.
    Returns {slot: tiktok_url} for every successfully uploaded image.
    """
    images: dict[str, str] = listing_item.get("listing", {}).get("images", {})
    result: dict[str, str] = {}

    for slot, url in images.items():
        if not url:
            continue
        if not url.startswith("/files/"):
            # Already a public URL — pass through unchanged
            result[slot] = url
            continue

        rel = url.removeprefix("/files/")
        file_path = (ROOT / rel).resolve()
        if not file_path.is_file():
            continue

        try:
            tiktok_url = upload_image_file(file_path)
            result[slot] = tiktok_url
            print(f"  ✓ {slot} → {tiktok_url[:60]}…")
        except RuntimeError as exc:
            print(f"  ✗ {slot}: {exc}")

    return result


def upload_all_listings(listing_config: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Upload images for every listing in the config. Returns {listing_id: {slot: url}}."""
    load_env_file()
    results: dict[str, dict[str, str]] = {}
    listings = listing_config.get("listings", [])
    for item in listings:
        lid = item.get("id", "")
        print(f"\n[{lid}] uploading…")
        urls = upload_listing_images(item)
        if urls:
            results[lid] = urls
    return results


if __name__ == "__main__":
    import sys
    load_env_file()
    if not check_credentials():
        print("Missing TikTok credentials. Set TIKTOK_APP_KEY, TIKTOK_APP_SECRET, TIKTOK_ACCESS_TOKEN in .env")
        sys.exit(1)
    # Quick test: upload a single file if provided
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        print(f"Uploading {path}…")
        try:
            url = upload_image_file(path)
            print(f"Success: {url}")
        except RuntimeError as e:
            print(f"Failed: {e}")
            sys.exit(1)
    else:
        print("Usage: python tiktok_media_upload.py <image_file>")
