# TikTok Shop Listing Automation

This workspace generates a TikTok Shop bulk upload workbook for INKERASTORY from structured source data.

## Files

- `data/inkerastory_listing.json` - editable product source data.
- `scripts/build_tiktok_bulk_upload.py` - fills the official TikTok template while preserving hidden sheets, validations, and formatting.
- `outputs/inkerastory_tiktok_bulk_upload.xlsx` - generated upload workbook.

## Generate The Workbook

```bash
python3 scripts/build_tiktok_bulk_upload.py
```

## Generate Image Prompts

Create a complete image prompt pack for both current themes:

```bash
python3 scripts/build_image_prompt_pack.py
```

Create prompts for only one theme:

```bash
python3 scripts/build_image_prompt_pack.py --theme world_cup
python3 scripts/build_image_prompt_pack.py --theme pets
```

Outputs:

- `outputs/image_prompt_pack.md` - human-readable prompt workflow.
- `outputs/image_prompt_manifest.json` - machine-readable prompt manifest.

The World Cup-inspired prompts intentionally avoid official FIFA marks, official tournament logos, team crests, player likenesses, and official uniforms. Use the generated images as custom wall-art marketing concepts, not as official tournament merchandise.

## Generate Images With The Agent

The image generation agent reads `data/image_workflows.json` and writes local image files plus a generation manifest.
Each theme currently generates 5 listing images: `main_image`, `image_2`, `image_3`, `image_4`, and `image_5`.

Put your API key in `.env`. Gemini is the default image provider:

```bash
GEMINI_API_KEY="your_gemini_api_key"
```

`.env` is ignored by git. Keep `.env.example` as the shareable template.

Test the workflow without an API call:

```bash
python3 scripts/image_generation_agent.py doctor
python3 scripts/image_generation_agent.py generate --theme pets --dry-run
python3 scripts/image_generation_agent.py generate --theme pets --mock --limit 1 --overwrite
python3 scripts/image_generation_agent.py status --theme pets
```

`--mock` only creates local placeholder PNGs so the visual workflow can be tested. It does not create real product-photo content.

Generate real images with Gemini:

```bash
python3 scripts/image_generation_agent.py generate --theme pets --overwrite
python3 scripts/image_generation_agent.py generate --theme world_cup --overwrite
```

To use the OpenAI Image API instead, add `OPENAI_API_KEY` to `.env` and pass `--provider openai`:

```bash
python3 scripts/image_generation_agent.py generate --provider openai --theme pets --quality high --overwrite
```

Default output:

- `outputs/generated_images/<theme>/*.png`
- `outputs/generated_images/generation_manifest.json`
- `outputs/generated_images/<theme>_image_urls.to_fill.json`

## Visual Listing Studio

Run the local visual control panel:

```bash
python3 scripts/listing_studio.py
```

Open:

```text
http://127.0.0.1:8765
```

The studio shows:

- whether `OPENAI_API_KEY` is loaded from `.env`
- which theme images are present or missing
- image previews from `outputs/generated_images/`
- prompts for each asset
- a multi-listing manager for creating, duplicating, deleting, and switching between products
- buttons for dry-run, mock generation, and live generation

The listing config supports multiple products in `data/inkerastory_listing.json` under `listings`.
Each product keeps its own product name, description, image URLs, theme, attributes, and SKUs.
Export writes every product's SKU rows into the same TikTok bulk upload workbook.

## Apply Generated Image URLs

After generating images and uploading them to TikTok Media Center or another public host, create a URL mapping like `data/image_urls.example.json`, then apply it:

```bash
python3 scripts/apply_image_urls.py --urls data/image_urls.example.json
python3 scripts/build_tiktok_bulk_upload.py
```

You can also paste TikTok Media Center URLs into a plain text file, one URL per line, in this order:

1. `main_image`
2. `image_2`
3. `image_3`
4. `image_4`
5. `image_5`

Then run:

```bash
python3 scripts/apply_image_urls.py --urls data/media_center_urls.example.txt
python3 scripts/build_tiktok_bulk_upload.py
```

## Before Uploading

Replace the placeholder image URLs in `data/inkerastory_listing.json` with real TikTok Media Center URLs or public image links, then regenerate the workbook.

The workbook currently uses `No brand` in the TikTok Brand field because the downloaded Seller Center template only includes `No brand` in its brand dropdown. Switch this back to `INKERASTORY` only after the brand is approved and available in a newly downloaded TikTok template.
