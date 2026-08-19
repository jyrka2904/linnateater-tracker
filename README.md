# Piletivaht v31

Built directly on v30.

## Image rule is now absolute

v31 removes all alternative image selection.

For every production, the ONLY permitted source is the image element used by
Tallinna Linnateater's repertoire/listing card. If that same element contains
`srcset`/`data-srcset`, the largest candidate from that same element may be
used. No image from the individual production page, gallery or Piletilevi may
replace it.

This guarantees that the stored image cannot suddenly become a different
press photo, cut-out person, alternate artwork, or artwork with a different
background.

The image is stored in PostgreSQL without cropping and without flattening
transparency onto a newly created background. A proportional downscale is the
only allowed transformation.

The worker rewrites the complete stored image library immediately on startup,
so old alternative images from previous versions are replaced automatically.

All v30 UI/calendar/background/font changes remain unchanged.
