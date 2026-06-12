#!/usr/bin/env python3
"""Apply generated image URLs to the TikTok listing source data."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


IMAGE_KEYS = [
    "main_image",
    "image_2",
    "image_3",
    "image_4",
    "image_5",
    "image_6",
    "image_7",
    "image_8",
    "image_9",
]


def is_public_url(value: str) -> bool:
    return value.startswith("https://") or value.startswith("http://")


def load_url_mapping(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        return data.get("images", data)

    urls = re.findall(r"https?://[^\s,;]+", text)
    if not urls:
        raise SystemExit(f"No image URLs found in {path}.")
    return {key: url for key, url in zip(IMAGE_KEYS, urls)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply image URLs to listing data.")
    parser.add_argument("--urls", required=True, help="JSON file containing an images object, or a text file with one image URL per line.")
    parser.add_argument("--listing", default="data/inkerastory_listing.json")
    args = parser.parse_args()

    urls_path = Path(args.urls)
    listing_path = Path(args.listing)
    listing_data = json.loads(listing_path.read_text(encoding="utf-8"))

    images = load_url_mapping(urls_path)
    if not images.get("main_image"):
        raise SystemExit("The image URL file must include images.main_image.")

    invalid = {
        key: value
        for key, value in images.items()
        if key in IMAGE_KEYS and value and not is_public_url(value)
    }
    if invalid:
        details = ", ".join(f"{key}={value}" for key, value in invalid.items())
        raise SystemExit(f"Image URLs must start with http:// or https://: {details}")

    current_images = listing_data.setdefault("listing", {}).setdefault("images", {})
    applied = []
    for key in IMAGE_KEYS:
        value = images.get(key)
        if value:
            current_images[key] = value
            applied.append(key)

    listing_path.write_text(json.dumps(listing_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Applied {len(applied)} image URLs to {listing_path}: {', '.join(applied)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
