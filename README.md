# Piletivaht v33

Built directly on v32.

Only the modal layout was changed:
- image source/storage logic is untouched;
- modal image keeps its own aspect ratio (`width:100%; height:auto`);
- no forced fixed-height image area, so no top/bottom letterbox bands;
- production title is now a separate block below the image instead of an absolute overlay;
- long production titles wrap and use a smaller responsive maximum font size;
- mobile forced modal image height was removed.
