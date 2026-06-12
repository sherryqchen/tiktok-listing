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

## Pet Portrait Memories

Evergreen emotional gift angle for dog, cat, and pet-owner memories.

Compliance notes:
- Use original-looking pets only, not famous internet pets or copyrighted characters.
- Show the canvas as a physical product, not just an AI portrait.
- Keep fur detail realistic and avoid exaggerated pet expressions.

### main_image - pets_01_main_clean_canvas.png

Kind: `listing-compliant`
Hook: A clean product-first image for the listing main image.

```text
Use case: product-mockup
Asset type: TikTok Shop main product image
Primary request: Create a clean ecommerce product image for INKERASTORY personalized pet portrait canvas wall art.
Scene/backdrop: pure white studio background, soft shadow only under the physical canvas, no clutter.
Subject: one rectangular stretched canvas showing a beautiful custom portrait of a dog and cat together, realistic fur detail, warm eye contact, printed on canvas with visible edge depth.
Composition: square 1:1, product centered, canvas fills about 85% of frame, front angle with slight side depth.
Style: premium ecommerce photography, bright clean light, high-resolution realistic canvas texture.
Text policy: no overlay text, no watermark, no platform UI.
Avoid: watermarks, QR codes, platform UI, distorted hands, tiny unreadable text, misleading scale, messy backgrounds, official sports logos, team crests, celebrity or athlete likenesses, copyrighted characters
```

### image_2 - pets_02_owner_reaction.png

Kind: `viral-creative`
Hook: Owner emotion drives saves and shares.

```text
Use case: ads-marketing
Asset type: TikTok Shop secondary product image / ad creative
Primary request: Create an emotional lifestyle image of a pet owner reacting to a personalized pet portrait canvas.
Scene/backdrop: cozy living room with soft daylight, pet bed and neutral decor.
Subject: a smiling pet owner holding a custom canvas portrait of their dog, with the real dog sitting nearby; the canvas must clearly look like the product.
Composition: square 1:1, canvas and dog are the focal points, human emotion visible but not overpowering the product.
Style: photorealistic natural lifestyle photography, warm and giftable, premium home decor mood.
Text policy: no overlay text, no watermark.
Avoid: watermarks, QR codes, platform UI, distorted hands, tiny unreadable text, misleading scale, messy backgrounds, official sports logos, team crests, celebrity or athlete likenesses, copyrighted characters
```

### image_3 - pets_03_memorial_keepsake.png

Kind: `viral-creative`
Hook: Gentle keepsake angle without feeling sad or heavy.

```text
Use case: ads-marketing
Asset type: TikTok Shop secondary product image
Primary request: Create a tasteful pet memorial keepsake scene for a custom pet portrait canvas.
Scene/backdrop: calm bedroom or reading corner, soft morning light, small flowers, neutral wall.
Subject: a rectangular canvas showing a beloved pet portrait, displayed respectfully on a wall or shelf; product is clear and premium.
Composition: square 1:1, peaceful emotional mood, canvas centered with a little surrounding decor.
Style: realistic lifestyle photography, gentle and warm, not dark, not overly sad.
Text policy: no overlay text, no watermark, no readable memorial dates.
Avoid: watermarks, QR codes, platform UI, distorted hands, tiny unreadable text, misleading scale, messy backgrounds, official sports logos, team crests, celebrity or athlete likenesses, copyrighted characters
```

### image_4 - pets_04_room_mockup.png

Kind: `listing-support`
Hook: Shows how pet art upgrades home decor.

```text
Use case: product-mockup
Asset type: TikTok Shop room mockup
Primary request: Create a modern room mockup for personalized pet portrait wall art.
Scene/backdrop: bright modern living room with a sofa, neutral tones, clean decor, soft daylight.
Subject: a large rectangular custom canvas portrait of a golden retriever and a tabby cat hanging above the sofa, realistic canvas texture and edge depth.
Composition: square 1:1, product large and centered, room gives scale but does not distract.
Style: premium interior photography, warm and sophisticated, realistic proportions.
Text policy: no overlay text, no watermark.
Avoid: watermarks, QR codes, platform UI, distorted hands, tiny unreadable text, misleading scale, messy backgrounds, official sports logos, team crests, celebrity or athlete likenesses, copyrighted characters
```
