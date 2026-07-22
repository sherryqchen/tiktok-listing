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
- buttons for AI copy generation, TikTok media upload, Shop API payload review, and draft submission

The listing config supports multiple products in `data/inkerastory_listing.json` under `listings`.
Each product keeps its own product name, description, image URLs, theme, attributes, and SKUs.
Export writes every product's SKU rows into the same TikTok bulk upload workbook.

## AI Copy And Shop API Listing

The end-to-end flow is:

1. Generate or paste product images in Listing Studio.
2. Click `AI 生成标题/五点/关键词` to update selected listings.
3. Click `上传所有图片到 TikTok 媒体库` if images are still local `/files/...` URLs.
4. Click `生成 Shop API Payload` and review the JSON files in `outputs/tiktok_shop_payloads/`.
5. Click `提交 TikTok Shop 草稿` only after payload review and TikTok credentials/category fields are configured.

Required `.env` values for AI copy:

```bash
OPENAI_API_KEY="your_openai_api_key"
OPENAI_TEXT_MODEL="gpt-5.1"
```

Required `.env` values for TikTok media upload:

```bash
TIKTOK_APP_KEY="your_app_key"
TIKTOK_APP_SECRET="your_app_secret"
TIKTOK_ACCESS_TOKEN="your_shop_access_token"
```

Required `.env` values for Shop API draft creation:

```bash
TIKTOK_SHOP_CIPHER="your_shop_cipher"
TIKTOK_CATEGORY_ID="your_category_id"
TIKTOK_WAREHOUSE_ID="your_warehouse_id"
TIKTOK_CURRENCY="USD"
TIKTOK_PRODUCT_SAVE_MODE="DRAFT"
```

CLI examples:

```bash
# Test AI copy locally without an API call
python3 scripts/listing_copy_agent.py --mock --apply

# Generate real AI copy for one listing
python3 scripts/listing_copy_agent.py --listing-id item_1 --apply

# Build reviewable Shop API payloads without submitting
python3 scripts/tiktok_shop_publish.py

# Submit selected listings to TikTok Shop as configured by TIKTOK_PRODUCT_SAVE_MODE
python3 scripts/tiktok_shop_publish.py --listing-id item_1 --submit
```

`scripts/tiktok_shop_publish.py` always writes the outgoing JSON to `outputs/tiktok_shop_payloads/` first. If your TikTok category requires extra product attributes, set `TIKTOK_CATEGORY_ATTRIBUTES_JSON` or add a per-listing `tiktok.category_attributes` array in `data/inkerastory_listing.json`.

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
