# Linnateater Tracker v17

## Faster repertoire again

v17 returns to the lightweight v10-style image strategy. The repertoire uses
the smaller card images from Linnateater's listing instead of large production
page images, so the browser has much less image data to decode and render.

## Blur fix

A few cards looked blurry because the parser could choose `<img src>` first.
On lazy-loaded pages that can be a blurred placeholder.

v17 now chooses:
1. the largest `data-srcset` / `srcset` candidate;
2. `data-src` / lazy-loaded source;
3. ordinary `src` only as a last fallback.

So the images remain lightweight without selecting the blurred placeholder.

## Cache migration

The first v17 worker start force-refreshes the cached image URLs so the large
v11-v16 images are replaced by the optimized card images.

All later features remain unchanged, including:
- multiple dates in one modal;
- Repertuaar / Minu jälgimised;
- password login;
- Twilio SMS alerts;
- v16 login-page headline spacing.

## Deploy

Replace v16 files with this ZIP. Railway, PostgreSQL and Twilio settings stay
unchanged.
