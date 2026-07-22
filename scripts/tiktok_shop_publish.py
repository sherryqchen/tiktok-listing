#!/usr/bin/env python3
"""Build and optionally submit TikTok Shop Create Product requests.

Default behavior is dry-run: write reviewable JSON payloads to outputs/ and do
not call TikTok. Live submission requires --submit plus TikTok credentials.

The modern TikTok Shop Open API schema varies by market/category. This module
keeps the endpoint, save mode, category attributes, warehouse, and image URI
mapping configurable through .env and per-listing `tiktok` fields.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "data" / "inkerastory_listing.json"
PAYLOAD_DIR = ROOT / "outputs" / "tiktok_shop_payloads"
DEFAULT_API_BASE = "https://open-api.tiktokglobalshop.com"
DEFAULT_CREATE_PATH = "/product/202309/products"
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


def env_json(name: str, default: Any) -> Any:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be valid JSON.") from exc


def check_credentials(require_publish_fields: bool = False) -> dict[str, Any]:
    load_env_file()
    required = ["TIKTOK_APP_KEY", "TIKTOK_APP_SECRET", "TIKTOK_ACCESS_TOKEN"]
    if require_publish_fields:
        required.extend(["TIKTOK_SHOP_CIPHER", "TIKTOK_CATEGORY_ID", "TIKTOK_WAREHOUSE_ID"])
    missing = [name for name in required if not os.environ.get(name)]
    return {
        "configured": not missing,
        "missing": missing,
        "base_url": os.environ.get("TIKTOK_API_BASE", DEFAULT_API_BASE),
        "create_path": os.environ.get("TIKTOK_PRODUCT_CREATE_PATH", DEFAULT_CREATE_PATH),
        "save_mode": os.environ.get("TIKTOK_PRODUCT_SAVE_MODE", "DRAFT"),
    }


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_filename(value: Any, fallback: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value or ""))
    return text.strip("_") or fallback


def money(value: Any) -> str:
    return f"{float(value):.2f}"


def dimension(value: Any) -> str:
    return f"{float(value):.2f}"


def listing_category_id(item: dict[str, Any]) -> str:
    listing = item.get("listing", {})
    tiktok = item.get("tiktok") or listing.get("tiktok") or {}
    return str(tiktok.get("category_id") or os.environ.get("TIKTOK_CATEGORY_ID") or "").strip()


def listing_brand_id(item: dict[str, Any]) -> str:
    listing = item.get("listing", {})
    tiktok = item.get("tiktok") or listing.get("tiktok") or {}
    return str(tiktok.get("brand_id") or os.environ.get("TIKTOK_BRAND_ID") or "").strip()


def listing_manufacturer_id(item: dict[str, Any]) -> str:
    listing = item.get("listing", {})
    tiktok = item.get("tiktok") or listing.get("tiktok") or {}
    return str(tiktok.get("manufacturer_id") or os.environ.get("TIKTOK_MANUFACTURER_ID") or "").strip()


def category_attributes(item: dict[str, Any]) -> list[dict[str, Any]]:
    listing = item.get("listing", {})
    tiktok = item.get("tiktok") or listing.get("tiktok") or {}
    attrs = []
    attrs.extend(env_json("TIKTOK_CATEGORY_ATTRIBUTES_JSON", []))
    attrs.extend(tiktok.get("category_attributes") or [])
    return attrs


def image_ref(item: dict[str, Any], slot: str, value: Any) -> dict[str, str] | None:
    listing = item.get("listing", {})
    tiktok = item.get("tiktok") or listing.get("tiktok") or {}
    image_uris = tiktok.get("image_uris") or listing.get("image_uris") or {}
    uri = image_uris.get(slot)
    if isinstance(value, dict):
        uri = value.get("uri") or uri
        url = value.get("url") or value.get("image_url") or ""
    else:
        url = str(value or "")
    if uri:
        return {"uri": str(uri)}
    if url:
        return {"uri": url}
    return None


def main_images(item: dict[str, Any]) -> list[dict[str, str]]:
    images = item.get("listing", {}).get("images", {})
    refs = []
    for slot in IMAGE_SLOTS:
        ref = image_ref(item, slot, images.get(slot))
        if ref:
            refs.append(ref)
    return refs[:9]


def size_sales_attribute(sku: dict[str, Any]) -> list[dict[str, Any]]:
    attrs = []
    if sku.get("type"):
        attrs.append({
            "name": "Type",
            "value_name": str(sku["type"]),
        })
    if sku.get("size"):
        attrs.append({
            "name": "Size",
            "value_name": str(sku["size"]),
        })
    return attrs


def sku_payload(item: dict[str, Any], sku: dict[str, Any]) -> dict[str, Any]:
    warehouse_id = os.environ.get("TIKTOK_WAREHOUSE_ID", "")
    quantity = int(item.get("listing", {}).get("warehouse_quantity_1", 100) or 100)
    payload = {
        "seller_sku": str(sku.get("seller_sku", "")),
        "price": {
            "amount": money(sku.get("price", 0)),
            "currency": os.environ.get("TIKTOK_CURRENCY", "USD"),
        },
        "inventory": [
            {
                "warehouse_id": warehouse_id,
                "quantity": quantity,
            }
        ],
        "sales_attributes": size_sales_attribute(sku),
    }
    sku_id = sku.get("id") or sku.get("sku_id")
    if sku_id:
        payload["id"] = str(sku_id)
    return payload


def first_sku(item: dict[str, Any]) -> dict[str, Any]:
    skus = item.get("skus") or []
    return skus[0] if skus else {}


def build_product_payload(item: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    listing = item.get("listing", {})
    skus = item.get("skus") or []
    warnings: list[str] = []
    images = main_images(item)
    sample = first_sku(item)

    category_id = listing_category_id(item)
    if not category_id:
        warnings.append("Missing TIKTOK_CATEGORY_ID or listing.tiktok.category_id.")
    if not images:
        warnings.append("No product images found.")
    if any(str(ref.get("uri", "")).startswith("http") for ref in images):
        warnings.append("Image refs are URLs; if TikTok returns image-uri errors, set listing.tiktok.image_uris after media upload.")
    if not skus:
        warnings.append("No SKUs found.")
    if not os.environ.get("TIKTOK_WAREHOUSE_ID"):
        warnings.append("Missing TIKTOK_WAREHOUSE_ID.")

    title = str(listing.get("product_name") or "Custom Canvas Print").strip()[:255]
    description = str(listing.get("product_description") or title).strip()

    payload: dict[str, Any] = {
        "save_mode": os.environ.get("TIKTOK_PRODUCT_SAVE_MODE", "DRAFT"),
        "title": title,
        "description": description,
        "category_id": category_id,
        "main_images": images,
        "skus": [sku_payload(item, sku) for sku in skus],
        "package_weight": {
            "value": dimension(sample.get("weight_lb", 0.6)),
            "unit": os.environ.get("TIKTOK_WEIGHT_UNIT", "POUND"),
        },
        "package_dimensions": {
            "length": dimension(sample.get("length_in", 12)),
            "width": dimension(sample.get("width_in", 9)),
            "height": dimension(sample.get("height_in", 1)),
            "unit": os.environ.get("TIKTOK_DIMENSION_UNIT", "INCH"),
        },
        "product_attributes": category_attributes(item),
    }

    brand_id = listing_brand_id(item)
    if brand_id:
        payload["brand_id"] = brand_id
    manufacturer_id = listing_manufacturer_id(item)
    if manufacturer_id:
        payload["manufacturer_ids"] = [manufacturer_id]

    warranty_period = os.environ.get("TIKTOK_WARRANTY_PERIOD")
    if warranty_period:
        payload["warranty_period"] = warranty_period

    delivery_option_ids = env_json("TIKTOK_DELIVERY_OPTION_IDS_JSON", [])
    if delivery_option_ids:
        payload["delivery_option_ids"] = delivery_option_ids

    return payload, warnings


def signed_url(path: str, body: bytes, params: dict[str, str]) -> str:
    app_secret = os.environ.get("TIKTOK_APP_SECRET", "")
    api_base = os.environ.get("TIKTOK_API_BASE", DEFAULT_API_BASE).rstrip("/")
    sign_params = {key: value for key, value in params.items() if key not in {"sign", "access_token"}}
    base = path + "".join(f"{key}{sign_params[key]}" for key in sorted(sign_params))
    if body:
        base += body.decode("utf-8")
    signature = hmac.new(
        app_secret.encode("utf-8"),
        f"{app_secret}{base}{app_secret}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    query = urllib.parse.urlencode({**params, "sign": signature})
    return f"{api_base}{path}?{query}"


def submit_create_product(payload: dict[str, Any]) -> dict[str, Any]:
    load_env_file()
    status = check_credentials(require_publish_fields=True)
    if not status["configured"]:
        raise RuntimeError("Missing TikTok credentials: " + ", ".join(status["missing"]))

    path = os.environ.get("TIKTOK_PRODUCT_CREATE_PATH", DEFAULT_CREATE_PATH)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    params = {
        "app_key": os.environ.get("TIKTOK_APP_KEY", ""),
        "timestamp": str(int(time.time())),
        "shop_cipher": os.environ.get("TIKTOK_SHOP_CIPHER", ""),
    }
    version = os.environ.get("TIKTOK_API_VERSION")
    if version:
        params["version"] = version
    url = signed_url(path, body, params)
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-tts-access-token": os.environ.get("TIKTOK_ACCESS_TOKEN", ""),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TikTok Shop API HTTP {exc.code}: {body_text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"TikTok Shop API network error: {exc}") from exc


def publish_config(
    config: dict[str, Any],
    listing_ids: list[str] | None = None,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    load_env_file()
    normalized = normalize_config(config)
    selected = set(listing_ids or [])
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    warnings: dict[str, list[str]] = {}
    payload_paths: dict[str, str] = {}

    for item in normalized.get("listings", []):
        item_id = str(item.get("id", ""))
        if selected and item_id not in selected:
            continue
        try:
            payload, item_warnings = build_product_payload(item)
            warnings[item_id] = item_warnings
            payload_path = PAYLOAD_DIR / f"{safe_filename(item_id, 'listing')}.json"
            write_json(payload_path, payload)
            payload_paths[item_id] = str(payload_path.relative_to(ROOT))
            if dry_run:
                results[item_id] = {"dry_run": True, "payload_path": payload_paths[item_id]}
            else:
                if item_warnings:
                    raise RuntimeError("Cannot submit while payload has warnings: " + "; ".join(item_warnings))
                response = submit_create_product(payload)
                results[item_id] = response
                tiktok = item.setdefault("tiktok", {})
                tiktok["last_submit_response"] = response
                tiktok["last_payload_path"] = payload_paths[item_id]
        except Exception as exc:
            errors[item_id] = str(exc)

    return {
        "ok": bool(results) and not errors,
        "config": normalized,
        "results": results,
        "errors": errors,
        "warnings": warnings,
        "payload_paths": payload_paths,
        "submitted": 0 if dry_run else len(results),
        "prepared": len(payload_paths),
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or submit TikTok Shop Create Product payloads.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Listing config JSON path.")
    parser.add_argument("--listing-id", action="append", dest="listing_ids", help="Listing ID to process. Repeatable.")
    parser.add_argument("--submit", action="store_true", help="Call TikTok Shop API. Omit for dry-run payload generation.")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    result = publish_config(config, args.listing_ids, dry_run=not args.submit)
    printable = {key: value for key, value in result.items() if key != "config"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0 if result["prepared"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
