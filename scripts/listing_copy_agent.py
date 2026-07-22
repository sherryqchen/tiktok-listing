#!/usr/bin/env python3
"""Generate TikTok listing copy from existing product images and listing data.

The script can run as a CLI or be imported by Listing Studio. It updates each
selected listing with:
  - listing.product_name
  - listing.product_description
  - listing.ai_copy.title / bullets / keywords / search_terms

Network calls happen only when OPENAI_API_KEY is configured.
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import mimetypes
import os
import re
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "data" / "inkerastory_listing.json"
RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.1"
IMAGE_SLOTS = ["main_image", "image_2", "image_3", "image_4", "image_5", "image_6"]


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


def check_openai_credentials() -> bool:
    load_env_file()
    return bool(os.environ.get("OPENAI_API_KEY"))


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    if "listings" in config:
        return copy.deepcopy(config)
    return {
        "template_path": config.get("template_path", "input_template.xlsx"),
        "output_path": config.get("output_path", "outputs/inkerastory_tiktok_bulk_upload.xlsx"),
        "active_listing_id": config.get("active_listing_id", "item_1"),
        "listings": [
            {
                "id": config.get("active_listing_id", "item_1"),
                "theme_id": config.get("theme_id", "pets"),
                "listing": config.get("listing", {}),
                "skus": config.get("skus", []),
                "sku_prefix": config.get("sku_prefix", ""),
            }
        ],
    }


def load_config(path: Path) -> dict[str, Any]:
    return normalize_config(json.loads(path.read_text(encoding="utf-8")))


def save_config(path: Path, config: dict[str, Any]) -> None:
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def local_file_from_url(url: str) -> Path | None:
    if not url.startswith("/files/"):
        return None
    rel = urllib.parse.unquote(url.removeprefix("/files/"))
    path = (ROOT / rel).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        return None
    return path if path.is_file() else None


def image_input_url(url: str) -> str | None:
    """Return a Responses-compatible image URL.

    Public URLs are passed through. Local Listing Studio /files URLs are inlined
    as data URLs so OpenAI can inspect generated product images.
    """
    url = str(url or "").strip()
    if not url:
        return None
    local = local_file_from_url(url)
    if local:
        mime = mimetypes.guess_type(local.name)[0] or "image/png"
        encoded = base64.b64encode(local.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    if url.startswith(("http://", "https://", "data:image/")):
        return url
    return None


def theme_label(theme_id: str, attrs: dict[str, Any]) -> str:
    team = attrs.get("team")
    labels = {
        "pets": "classic custom pet portrait canvas",
        "pets_original": "custom pet photo canvas print",
        "pets_royal": "AI royal pet portrait canvas",
        "pets_anime": "AI anime pet portrait canvas",
        "pets_world_cup": f"custom pet soccer jersey canvas ({team or 'team colors'})",
        "people": "personalized family or couple portrait canvas",
        "world_cup": "custom soccer fan memory canvas",
    }
    return labels.get(theme_id, theme_id.replace("_", " "))


def listing_context(item: dict[str, Any]) -> dict[str, Any]:
    listing = item.get("listing", {})
    attrs = listing.get("attributes", {})
    prices = [float(sku.get("price", 0)) for sku in item.get("skus", []) if sku.get("price") is not None]
    sizes = sorted({str(sku.get("size", "")) for sku in item.get("skus", []) if sku.get("size")})
    product_types = sorted({str(sku.get("type", "")) for sku in item.get("skus", []) if sku.get("type")})
    return {
        "listing_id": item.get("id", ""),
        "theme_id": item.get("theme_id", ""),
        "theme": theme_label(item.get("theme_id", ""), attrs),
        "brand": listing.get("brand", "No brand"),
        "current_title": listing.get("product_name", ""),
        "current_description": listing.get("product_description", ""),
        "category": listing.get("category", ""),
        "attributes": attrs,
        "sizes": sizes,
        "product_types": product_types,
        "price_range": {
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
        },
    }


def build_prompt(item: dict[str, Any]) -> str:
    context = listing_context(item)
    return textwrap.dedent(
        f"""
        You are writing TikTok Shop listing copy for INKERASTORY, a personalized
        canvas and print shop.

        Use the product images and JSON context to create conversion-focused,
        policy-safe copy for a TikTok Shop product listing.

        Requirements:
        - US English.
        - Title should be <= 180 characters.
        - Write exactly 5 bullet points. Each bullet <= 170 characters.
        - Keywords should be 12 to 20 short search phrases.
        - Avoid unverifiable claims such as guaranteed delivery dates.
        - Avoid official sports marks, tournament names, celebrity names, and
          team crests/logos unless they are generic descriptive words.
        - Keep the product clearly positioned as personalized printed wall art.
        - Mention upload photo/customization where relevant.
        - Do not include markdown fences.

        Return only valid JSON with this shape:
        {{
          "title": "...",
          "bullets": ["...", "...", "...", "...", "..."],
          "keywords": ["...", "..."],
          "search_terms": "...",
          "description": "A concise TikTok-ready description using the 5 bullets."
        }}

        Listing context:
        {json.dumps(context, ensure_ascii=False, indent=2)}
        """
    ).strip()


def extract_text_from_response(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks: list[str] = []
    for output in data.get("output", []) or []:
        for content in output.get("content", []) or []:
            if isinstance(content, dict):
                if isinstance(content.get("text"), str):
                    chunks.append(content["text"])
                elif isinstance(content.get("output_text"), str):
                    chunks.append(content["output_text"])
    return "\n".join(chunks).strip()


def parse_json_text(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def sanitize_copy(data: dict[str, Any], fallback_title: str) -> dict[str, Any]:
    title = str(data.get("title") or fallback_title).strip()
    title = re.sub(r"\s+", " ", title)[:180]

    bullets = data.get("bullets") if isinstance(data.get("bullets"), list) else []
    clean_bullets = [re.sub(r"\s+", " ", str(item)).strip()[:170] for item in bullets if str(item).strip()]
    while len(clean_bullets) < 5:
        clean_bullets.append(
            [
                "Personalized canvas or print made from your uploaded photo.",
                "Premium wall art for gifts, keepsakes, and home decor.",
                "Choose print only or stretched canvas in multiple sizes.",
                "Made to order with clean, gift-ready presentation.",
                "Great for birthdays, holidays, memorials, and special moments.",
            ][len(clean_bullets)]
        )
    clean_bullets = clean_bullets[:5]

    keywords = data.get("keywords") if isinstance(data.get("keywords"), list) else []
    clean_keywords = [re.sub(r"\s+", " ", str(item)).strip().lower() for item in keywords if str(item).strip()]
    seen: set[str] = set()
    deduped_keywords = []
    for keyword in clean_keywords:
        if keyword in seen:
            continue
        seen.add(keyword)
        deduped_keywords.append(keyword[:60])
    if len(deduped_keywords) < 8:
        deduped_keywords.extend([
            "custom canvas print",
            "personalized wall art",
            "photo canvas",
            "custom portrait",
            "pet portrait gift",
            "home decor gift",
            "print only poster",
            "stretched canvas",
        ])
    deduped_keywords = deduped_keywords[:20]

    search_terms = str(data.get("search_terms") or ", ".join(deduped_keywords)).strip()
    description = str(data.get("description") or "").strip()
    if not description:
        description = compose_description(title, clean_bullets, deduped_keywords)

    return {
        "title": title,
        "bullets": clean_bullets,
        "keywords": deduped_keywords,
        "search_terms": search_terms[:500],
        "description": description.strip(),
    }


def compose_description(title: str, bullets: list[str], keywords: list[str]) -> str:
    bullet_text = "\n".join(f"- {bullet}" for bullet in bullets)
    keyword_text = ", ".join(keywords[:12])
    return (
        f"{title}\n\n"
        f"Product Highlights:\n{bullet_text}\n\n"
        "How It Works:\n"
        "1. Place your order and choose size/type.\n"
        "2. Upload a clear photo and optional personalization notes.\n"
        "3. We create your custom artwork and print it as wall art.\n\n"
        f"Search Keywords: {keyword_text}"
    )


def post_openai_request(request_body: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    req = urllib.request.Request(
        RESPONSES_ENDPOINT,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI API network error: {exc}") from exc


def call_openai_for_copy(item: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    load_env_file()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    listing = item.get("listing", {})
    image_urls = [
        image_input_url(listing.get("images", {}).get(slot, ""))
        for slot in IMAGE_SLOTS
    ]
    images = [url for url in image_urls if url]
    if not images:
        raise RuntimeError(f"{item.get('id', 'listing')} has no usable product images.")

    content: list[dict[str, Any]] = [{"type": "input_text", "text": build_prompt(item)}]
    for url in images[:6]:
        content.append({"type": "input_image", "image_url": url})

    request_body = {
        "model": model or os.environ.get("OPENAI_TEXT_MODEL", DEFAULT_MODEL),
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "tiktok_listing_copy",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "bullets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 5,
                            "maxItems": 5,
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 8,
                            "maxItems": 20,
                        },
                        "search_terms": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["title", "bullets", "keywords", "search_terms", "description"],
                },
            }
        },
    }

    try:
        data = post_openai_request(request_body)
    except RuntimeError as exc:
        # Fallback for accounts/models that reject schema-constrained output.
        if "HTTP 400" not in str(exc):
            raise
        fallback_body = copy.deepcopy(request_body)
        fallback_body.pop("text", None)
        data = post_openai_request(fallback_body)

    text = extract_text_from_response(data)
    parsed = parse_json_text(text)
    return sanitize_copy(parsed, listing.get("product_name", "Custom Canvas Print"))


def mock_copy(item: dict[str, Any]) -> dict[str, Any]:
    context = listing_context(item)
    title = f"{context['theme'].title()} | Personalized Photo Wall Art | INKERASTORY"
    bullets = [
        "Personalized wall art made from your uploaded photo.",
        "Premium HD print quality for clean, gift-ready presentation.",
        "Choose print only or stretched canvas in multiple sizes.",
        "Made for birthdays, holidays, memorials, and home decor.",
        "Simple upload process with optional name, date, or note.",
    ]
    keywords = [
        "custom canvas print",
        "personalized wall art",
        "photo canvas",
        "custom portrait",
        "pet portrait gift",
        "home decor gift",
        "stretched canvas",
        "print only poster",
        "personalized gift",
        "inkerastory canvas",
    ]
    return {
        "title": title[:180],
        "bullets": bullets,
        "keywords": keywords,
        "search_terms": ", ".join(keywords),
        "description": compose_description(title[:180], bullets, keywords),
    }


def apply_copy_to_listing(item: dict[str, Any], generated: dict[str, Any]) -> None:
    listing = item.setdefault("listing", {})
    listing["product_name"] = generated["title"]
    listing["product_description"] = generated["description"]
    listing["ai_copy"] = {
        "title": generated["title"],
        "bullets": generated["bullets"],
        "keywords": generated["keywords"],
        "search_terms": generated["search_terms"],
    }
    listing.setdefault("attributes", {})["search_keywords"] = ", ".join(generated["keywords"][:12])


def generate_copy_for_config(
    config: dict[str, Any],
    listing_ids: list[str] | None = None,
    *,
    model: str | None = None,
    mock: bool = False,
) -> dict[str, Any]:
    normalized = normalize_config(config)
    selected = set(listing_ids or [])
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for item in normalized.get("listings", []):
        item_id = str(item.get("id", ""))
        if selected and item_id not in selected:
            continue
        try:
            generated = mock_copy(item) if mock else call_openai_for_copy(item, model=model)
            apply_copy_to_listing(item, generated)
            results[item_id] = generated
        except Exception as exc:
            errors[item_id] = str(exc)

    return {
        "ok": bool(results) and not errors,
        "config": normalized,
        "results": results,
        "errors": errors,
        "updated": len(results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate TikTok listing copy with OpenAI.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Listing config JSON path.")
    parser.add_argument("--listing-id", action="append", dest="listing_ids", help="Listing ID to process. Repeatable.")
    parser.add_argument("--model", default=None, help="OpenAI text/vision model. Defaults to OPENAI_TEXT_MODEL or gpt-5.1.")
    parser.add_argument("--mock", action="store_true", help="Generate deterministic local copy without calling OpenAI.")
    parser.add_argument("--apply", action="store_true", help="Write generated copy back to the config file.")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    result = generate_copy_for_config(config, args.listing_ids, model=args.model, mock=args.mock)
    if args.apply and result["updated"]:
        save_config(config_path, result["config"])

    printable = {key: value for key, value in result.items() if key != "config"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0 if result["updated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
