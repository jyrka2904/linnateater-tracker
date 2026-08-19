# Piletivaht v30

Built directly on v29.

Changes:
- restored the old warm off-white page background (#efede8) for logged-in pages;
- restored the login split to solid red left + warm off-white right;
- made Repertuaar / Minu jälgimised navigation larger;
- made the phone number beside Logi välja larger;
- unified typography around Segoe UI / Arial / Helvetica;
- replaced native date inputs with a small Estonian/European calendar whose week is E T K N R L P (Monday–Sunday);
- production image storage now treats the repertoire thumbnail as the visual source of truth;
- a larger production-page image may be used only when a strict perceptual comparison says it is the same visual;
- otherwise the repertoire image is stored unchanged;
- transparent images remain transparent instead of being flattened to black.

No other tracker, Twilio, performance-cache or monitoring logic was changed.
