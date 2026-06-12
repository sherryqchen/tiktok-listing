#!/usr/bin/env python3
"""Generate INKERASTORY listing images from the configured prompt workflows.

The agent has three practical modes:

- dry-run: build a generation plan without calling an API
- mock: create local placeholder PNGs for workflow testing
- live: call Gemini or the OpenAI Image API using the matching API key
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import struct
import time
import urllib.error
import urllib.request
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from build_image_prompt_pack import build_manifest, load_config, selected_themes


DEFAULT_CONFIG = Path("data/image_workflows.json")
DEFAULT_OUTPUT_DIR = Path("outputs/generated_images")
DEFAULT_PROVIDER = "gemini"
DEFAULT_OPENAI_MODEL = "gpt-image-1.5"
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-image"
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "medium"
DEFAULT_FORMAT = "png"
OPENAI_IMAGE_ENDPOINT = "https://api.openai.com/v1/images/generations"
GEMINI_IMAGE_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1/models/{model}:generateContent"


def load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (key not in os.environ or not os.environ.get(key)):
            os.environ[key] = value


@dataclass
class GenerationOptions:
    provider: str
    model: str
    size: str
    quality: str
    output_format: str
    output_compression: int | None
    moderation: str
    timeout: int
    overwrite: bool
    dry_run: bool
    mock: bool


def parse_size(size: str) -> tuple[int, int] | None:
    if size == "auto":
        return None
    allowed = {"1024x1024", "1536x1024", "1024x1536"}
    if size not in allowed:
        raise SystemExit(f"Invalid size {size!r}. Use one of: {', '.join(sorted(allowed))}, or auto.")
    if "x" not in size:
        raise SystemExit(f"Invalid size {size!r}. Expected format like 1024x1024 or 2048x2048.")
    width_text, height_text = size.lower().split("x", 1)
    return int(width_text), int(height_text)


def output_suffix(output_format: str) -> str:
    return {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp"}[output_format]


def asset_output_path(output_dir: Path, asset: dict[str, Any], output_format: str) -> Path:
    filename = Path(asset["filename"]).with_suffix(output_suffix(output_format)).name
    return output_dir / asset["theme_id"] / filename


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", binascii.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def write_mock_png(path: Path, size: str, label_seed: str) -> None:
    dimensions = parse_size(size) or (1024, 1024)
    width, height = dimensions
    # Deterministic but visibly different soft colors per asset.
    seed = sum(ord(char) for char in label_seed)
    red = 210 + seed % 30
    green = 215 + (seed // 3) % 25
    blue = 220 + (seed // 7) % 20
    row = b"\x00" + bytes([red, green, blue]) * width
    raw = row * height
    png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw, level=9))
        + png_chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def read_png_dimensions(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 24:
        return None
    return struct.unpack(">II", data[16:24])


def request_openai_image(asset: dict[str, Any], options: GenerationOptions) -> tuple[bytes, dict[str, Any]]:
    load_env_file()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set. Use --dry-run or --mock to test without calling the API.")

    payload: dict[str, Any] = {
        "model": options.model,
        "prompt": asset["prompt"],
        "size": options.size,
        "quality": options.quality,
        "output_format": options.output_format,
        "moderation": options.moderation,
        "n": 1,
    }
    if options.output_compression is not None and options.output_format in {"jpeg", "webp"}:
        payload["output_compression"] = options.output_compression

    request_id = f"inkerastory-image-agent-{uuid.uuid4()}"
    request = urllib.request.Request(
        OPENAI_IMAGE_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Client-Request-Id": request_id,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=options.timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
            response_request_id = response.headers.get("x-request-id")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"OpenAI image request failed with HTTP {error.code}:\n{body}") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"OpenAI image request failed: {error}") from error

    image_base64 = response_data.get("data", [{}])[0].get("b64_json")
    if not image_base64:
        raise SystemExit(f"OpenAI response did not include data[0].b64_json:\n{json.dumps(response_data)[:1000]}")
    metadata = {
        "openai_request_id": response_request_id,
        "client_request_id": request_id,
        "revised_prompt": response_data.get("data", [{}])[0].get("revised_prompt"),
    }
    return base64.b64decode(image_base64), metadata


def request_gemini_image(asset: dict[str, Any], options: GenerationOptions) -> tuple[bytes, dict[str, Any]]:
    load_env_file()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set. Add it to .env, or use --dry-run / --mock to test without calling the API.")
    if options.output_format != "png":
        raise SystemExit("Gemini generation currently saves PNG files in this workflow. Use --output-format png.")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": asset["prompt"]},
                ],
            }
        ]
    }
    request = urllib.request.Request(
        GEMINI_IMAGE_ENDPOINT_TEMPLATE.format(model=options.model),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=options.timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Gemini image request failed with HTTP {error.code}:\n{body}") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Gemini image request failed: {error}") from error

    parts = response_data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text_parts: list[str] = []
    for part in parts:
        if part.get("text"):
            text_parts.append(part["text"])
            continue
        inline_data = part.get("inlineData") or part.get("inline_data")
        if inline_data and inline_data.get("data"):
            metadata = {
                "gemini_model": options.model,
                "gemini_mime_type": inline_data.get("mimeType") or inline_data.get("mime_type"),
            }
            if text_parts:
                metadata["gemini_text"] = "\n".join(text_parts)
            return base64.b64decode(inline_data["data"]), metadata

    raise SystemExit(f"Gemini response did not include image inlineData:\n{json.dumps(response_data)[:1000]}")


def request_image(asset: dict[str, Any], options: GenerationOptions) -> tuple[bytes, dict[str, Any]]:
    if options.provider == "gemini":
        return request_gemini_image(asset, options)
    if options.provider == "openai":
        return request_openai_image(asset, options)
    raise SystemExit(f"Unsupported provider: {options.provider}")


def validate_output(path: Path, options: GenerationOptions) -> dict[str, Any]:
    result: dict[str, Any] = {"exists": path.exists(), "path": str(path)}
    if not path.exists():
        result["ok"] = False
        result["reason"] = "file missing"
        return result
    result["bytes"] = path.stat().st_size
    if options.output_format == "png":
        dimensions = read_png_dimensions(path)
        result["dimensions"] = list(dimensions) if dimensions else None
        expected = parse_size(options.size)
        result["ok"] = bool(dimensions) and (expected is None or dimensions == expected)
        if not result["ok"]:
            result["reason"] = f"expected PNG dimensions {expected}, got {dimensions}"
    else:
        result["ok"] = result["bytes"] > 0
    return result


def write_url_templates(output_dir: Path, records: list[dict[str, Any]]) -> list[Path]:
    by_theme: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_theme.setdefault(record["theme_id"], []).append(record)

    paths = []
    for theme_id, theme_records in by_theme.items():
        images = {
            record["slot"]: f"https://your-public-image-host/{Path(record['output_path']).name}"
            for record in sorted(theme_records, key=lambda item: item["slot"])
            if record["slot"].startswith("image_") or record["slot"] == "main_image"
        }
        path = output_dir / f"{theme_id}_image_urls.to_fill.json"
        path.write_text(json.dumps({"theme_id": theme_id, "images": images}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def select_assets(config_path: Path, theme: str | None, slots: set[str] | None) -> list[dict[str, Any]]:
    config = load_config(config_path)
    themes = selected_themes(config, theme)
    manifest = build_manifest(config, themes)
    assets = manifest["assets"]
    if slots:
        assets = [asset for asset in assets if asset["slot"] in slots]
    return assets


def run_generate(args: argparse.Namespace) -> int:
    slots = set(args.slot or []) or None
    assets = select_assets(Path(args.config), args.theme, slots)
    if args.limit:
        assets = assets[: args.limit]
    if not assets:
        raise SystemExit("No assets selected.")

    if getattr(args, "prompt", None):
        if not slots or len(slots) != 1:
            raise SystemExit("--prompt requires exactly one --slot.")
        for asset in assets:
            asset["prompt"] = args.prompt

    options = GenerationOptions(
        provider=args.provider,
        model=args.model,
        size=args.size,
        quality=args.quality,
        output_format=args.output_format,
        output_compression=args.output_compression,
        moderation=args.moderation,
        timeout=args.timeout,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        mock=args.mock,
    )
    if args.provider == "gemini" and options.output_format != "png":
        raise SystemExit("Gemini provider currently supports --output-format png in this workflow.")
    if options.mock and options.output_format != "png":
        raise SystemExit("--mock only supports --output-format png because it creates local PNG placeholders.")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for index, asset in enumerate(assets, start=1):
        out_path = asset_output_path(output_dir, asset, options.output_format)
        record = {
            "theme_id": asset["theme_id"],
            "slot": asset["slot"],
            "kind": asset["kind"],
            "filename": Path(out_path).name,
            "output_path": str(out_path),
            "model": options.model,
            "provider": options.provider,
            "size": options.size,
            "quality": options.quality,
            "output_format": options.output_format,
            "prompt": asset["prompt"],
            "status": "planned",
        }
        print(f"[{index}/{len(assets)}] {asset['theme_id']}:{asset['slot']} -> {out_path}")

        if out_path.exists() and not options.overwrite and not options.dry_run:
            record["status"] = "skipped_exists"
            record["validation"] = validate_output(out_path, options)
            records.append(record)
            continue

        if options.dry_run:
            records.append(record)
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)
        if options.mock:
            write_mock_png(out_path, options.size, asset["filename"])
            record["status"] = "mocked"
        else:
            image_bytes, metadata = request_image(asset, options)
            out_path.write_bytes(image_bytes)
            record.update(metadata)
            record["status"] = "generated"

        record["validation"] = validate_output(out_path, options)
        records.append(record)

    manifest_path = output_dir / "generation_manifest.json"
    manifest_payload = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "dry_run" if options.dry_run else "mock" if options.mock else "live",
        "assets": records,
    }
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    url_template_paths = write_url_templates(output_dir, records)

    print(f"Wrote generation manifest: {manifest_path}")
    for path in url_template_paths:
        print(f"Wrote URL template: {path}")
    return 0


def run_status(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    assets = select_assets(Path(args.config), args.theme, set(args.slot or []) or None)
    found = 0
    for asset in assets:
        path = asset_output_path(output_dir, asset, args.output_format)
        status = "present" if path.exists() else "missing"
        found += int(path.exists())
        print(f"{status:8} {asset['theme_id']}:{asset['slot']} {path}")
    print(f"{found}/{len(assets)} files present")
    return 0


def run_doctor(args: argparse.Namespace) -> int:
    load_env_file(Path(args.env))
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    output_dir = Path(args.output_dir)
    assets = select_assets(Path(args.config), args.theme, set(args.slot or []) or None)
    present = 0
    print("Image generation doctor")
    print(f"- config: {args.config}")
    print(f"- .env exists: {Path(args.env).exists()}")
    print(f"- default provider: {DEFAULT_PROVIDER}")
    print(f"- GEMINI_API_KEY loaded: {bool(gemini_key)}")
    if gemini_key:
        print(f"- GEMINI_API_KEY hint: ...{gemini_key[-4:]}")
    print(f"- OPENAI_API_KEY loaded: {bool(openai_key)}")
    if openai_key:
        print(f"- OPENAI_API_KEY hint: ...{openai_key[-4:]}")
    print(f"- default Gemini model: {DEFAULT_GEMINI_MODEL}")
    print(f"- default OpenAI model: {DEFAULT_OPENAI_MODEL}")
    print(f"- default size: {DEFAULT_SIZE}")
    print("- supported sizes: 1024x1024, 1536x1024, 1024x1536, auto")
    for asset in assets:
        path = asset_output_path(output_dir, asset, args.output_format)
        if path.exists():
            present += 1
    print(f"- selected files present: {present}/{len(assets)}")
    if not gemini_key:
        print("Next: add GEMINI_API_KEY to .env, then use live Gemini generation.")
    print("Note: --mock creates placeholder PNGs only. It will not create real product-photo content.")
    return 0


def default_model_for_provider(provider: str) -> str:
    if provider == "gemini":
        return DEFAULT_GEMINI_MODEL
    if provider == "openai":
        return DEFAULT_OPENAI_MODEL
    raise SystemExit(f"Unsupported provider: {provider}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="INKERASTORY image generation agent.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Generate images or create a dry-run plan.")
    generate.add_argument("--config", default=str(DEFAULT_CONFIG))
    generate.add_argument("--theme", choices=["world_cup", "pets", "pets_original", "pets_royal", "pets_anime", "people"], help="Theme to generate. Omit for all themes.")
    generate.add_argument("--prompt", help="Override the prompt for the selected slot (requires exactly one --slot).")
    generate.add_argument("--slot", action="append", help="Asset slot to generate, e.g. main_image. Repeatable.")
    generate.add_argument("--limit", type=int, help="Generate only the first N selected assets.")
    generate.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    generate.add_argument("--provider", choices=["gemini", "openai"], default=DEFAULT_PROVIDER)
    generate.add_argument("--model")
    generate.add_argument("--size", default=DEFAULT_SIZE)
    generate.add_argument("--quality", choices=["low", "medium", "high", "auto"], default=DEFAULT_QUALITY)
    generate.add_argument("--output-format", choices=["png", "jpeg", "webp"], default=DEFAULT_FORMAT)
    generate.add_argument("--output-compression", type=int, choices=range(0, 101), metavar="0-100")
    generate.add_argument("--moderation", choices=["auto", "low"], default="auto")
    generate.add_argument("--timeout", type=int, default=180)
    generate.add_argument("--overwrite", action="store_true")
    generate.add_argument("--dry-run", action="store_true", help="Write a plan but do not call the API or create images.")
    generate.add_argument("--mock", action="store_true", help="Create local placeholder PNGs for workflow testing.")
    generate.set_defaults(func=run_generate)

    status = subparsers.add_parser("status", help="Show which expected image files exist.")
    status.add_argument("--config", default=str(DEFAULT_CONFIG))
    status.add_argument("--theme", choices=["world_cup", "pets", "pets_original", "pets_royal", "pets_anime", "people"], help="Theme to inspect. Omit for all themes.")
    status.add_argument("--slot", action="append", help="Asset slot to inspect. Repeatable.")
    status.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    status.add_argument("--output-format", choices=["png", "jpeg", "webp"], default=DEFAULT_FORMAT)
    status.set_defaults(func=run_status)

    doctor = subparsers.add_parser("doctor", help="Check environment and generation settings.")
    doctor.add_argument("--config", default=str(DEFAULT_CONFIG))
    doctor.add_argument("--theme", choices=["world_cup", "pets", "pets_original", "pets_royal", "pets_anime", "people"], help="Theme to inspect. Omit for all themes.")
    doctor.add_argument("--slot", action="append", help="Asset slot to inspect. Repeatable.")
    doctor.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    doctor.add_argument("--output-format", choices=["png", "jpeg", "webp"], default=DEFAULT_FORMAT)
    doctor.add_argument("--env", default=".env")
    doctor.set_defaults(func=run_doctor)

    return parser


def main() -> int:
    load_env_file()
    parser = build_parser()
    args = parser.parse_args()
    if hasattr(args, "provider") and not args.model:
        args.model = default_model_for_provider(args.provider)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
