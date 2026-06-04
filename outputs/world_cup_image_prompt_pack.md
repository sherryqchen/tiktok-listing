# INKERASTORY Image Prompt Pack

Brand: INKERASTORY
Product: personalized photo and quote canvas print
Target: TikTok Shop buyers looking for personalized wall art and meaningful gifts

## Workflow

1. Generate images from the prompts below.
2. Review for product clarity, no official logos, no watermarks, and no misleading scale.
3. Upload approved images to TikTok Shop Media Center or another public image host.
4. Paste the final image URLs into `data/inkerastory_listing.json`.
5. Run `python3 scripts/build_tiktok_bulk_upload.py` to regenerate the upload workbook.

## Global Avoid List

- watermarks
- QR codes
- platform UI
- distorted hands
- tiny unreadable text
- misleading scale
- messy backgrounds
- official sports logos
- team crests
- celebrity or athlete likenesses
- copyrighted characters

## World Cup Inspired Soccer Memories

Seasonal soccer fever gift angle for the June 11 to July 19, 2026 global tournament window, without official FIFA marks.

Compliance notes:
- Use generic international soccer championship language in prompts.
- Do not include the FIFA logo, World Cup logo, official trophy, official mascot, official posters, team crests, player likenesses, or national team uniforms.
- Use generic scarves, face paint, soccer balls, green field mood, and family fan moments.

### main_image - world_cup_01_main_clean_canvas.png

Kind: `listing-compliant`
Hook: A clean product-first image for the listing main image.

```text
Use case: product-mockup
Asset type: TikTok Shop main product image
Primary request: Create a clean ecommerce product image for INKERASTORY personalized canvas wall art inspired by international soccer celebration season.
Scene/backdrop: pure white studio background, soft shadow only under the physical product, no props touching the product.
Subject: one rectangular stretched canvas showing a tasteful generic family soccer celebration photo transformed into wall art; no readable official logos, no team crests, no player likenesses, no FIFA or World Cup marks.
Composition: square 1:1, product centered, canvas fills about 85% of the frame, crisp front angle with slight depth visible on the canvas edge.
Style: premium ecommerce photography, bright clean light, high-resolution realistic print texture.
Text policy: no overlay text, no watermark, no logos except no visible brand logo.
Avoid: watermarks, QR codes, platform UI, distorted hands, tiny unreadable text, misleading scale, messy backgrounds, official sports logos, team crests, celebrity or athlete likenesses, copyrighted characters
```

### image_2 - world_cup_02_fan_story_room.png

Kind: `viral-creative`
Hook: Turns match-day emotion into a wall-art memory.

```text
Use case: ads-marketing
Asset type: TikTok Shop secondary product image / ad creative
Primary request: Create a scroll-stopping lifestyle image for a personalized soccer memory canvas.
Scene/backdrop: warm living room watch-party scene, friends and family celebrating a goal, green and neutral decor, generic soccer scarves with no official marks.
Subject: a framed INKERASTORY-style canvas on the wall showing a custom family soccer celebration photo, clearly visible as the product.
Composition: square 1:1, canvas is the focal point, people are secondary and slightly behind or beside it, energetic but not cluttered.
Style: realistic lifestyle photography, bright celebratory mood, premium home decor aesthetic.
Text policy: no in-image text, no watermarks, no official sports logos, no team names.
Avoid: watermarks, QR codes, platform UI, distorted hands, tiny unreadable text, misleading scale, messy backgrounds, official sports logos, team crests, celebrity or athlete likenesses, copyrighted characters
```

### image_3 - world_cup_03_gift_unboxing.png

Kind: `viral-creative`
Hook: Gift angle for soccer fans.

```text
Use case: ads-marketing
Asset type: TikTok Shop secondary image
Primary request: Create an emotional gift-unboxing scene for a custom soccer fan canvas print.
Scene/backdrop: modern home, neutral table, simple gift box, subtle green field-inspired accents.
Subject: a person opening a gift box and revealing a personalized canvas with a generic soccer family photo and custom quote area, no readable official text or sports marks.
Composition: square 1:1, hands and gift box in foreground, canvas upright and legible as the product, warm human emotion.
Style: photorealistic natural light, premium gift photography, high clarity.
Text policy: avoid readable text except a vague short custom quote shape if necessary; no watermarks, no official tournament or team branding.
Avoid: watermarks, QR codes, platform UI, distorted hands, tiny unreadable text, misleading scale, messy backgrounds, official sports logos, team crests, celebrity or athlete likenesses, copyrighted characters
```

### image_4 - world_cup_04_size_wall_mockup.png

Kind: `listing-support`
Hook: Shows size options without making the product feel small.

```text
Use case: product-mockup
Asset type: TikTok Shop size comparison image
Primary request: Create a clean wall mockup showing four personalized soccer memory canvas sizes.
Scene/backdrop: bright modern wall above a simple console table, minimal decor.
Subject: four rectangular canvases in increasing sizes, each showing a different generic soccer celebration memory photo, no official logos or team crests.
Composition: square 1:1, clear size progression from small to large, enough spacing, product remains premium.
Style: realistic room mockup, neutral palette with small energetic green accents.
Text policy: no labels or overlay text; leave room if a designer later adds size labels.
Avoid: watermarks, QR codes, platform UI, distorted hands, tiny unreadable text, misleading scale, messy backgrounds, official sports logos, team crests, celebrity or athlete likenesses, copyrighted characters
```

### image_5 - world_cup_05_print_vs_canvas.png

Kind: `listing-support`
Hook: Explains Print Only vs Stretched Canvas visually.

```text
Use case: product-mockup
Asset type: TikTok Shop comparison image
Primary request: Create a side-by-side product comparison for personalized soccer memory wall art: Print Only versus Stretched Canvas.
Scene/backdrop: clean neutral studio surface with soft light.
Subject: left side is a rolled or flat premium art print with a generic soccer fan photo; right side is a stretched canvas version with visible edge depth and canvas texture.
Composition: square 1:1, balanced side-by-side layout, physical material difference is obvious.
Style: premium ecommerce product photography, realistic paper and canvas texture.
Text policy: no overlay text, no watermarks, no official marks.
Avoid: watermarks, QR codes, platform UI, distorted hands, tiny unreadable text, misleading scale, messy backgrounds, official sports logos, team crests, celebrity or athlete likenesses, copyrighted characters
```
