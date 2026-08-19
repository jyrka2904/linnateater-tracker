# Piletivaht v35

Built directly on v34.

Availability fixes only:

- fixes Linnateater soft-hyphen titles such as `Seitsmemagaja­päev` and
  `Südame­harjutus`; invisible discretionary hyphens are now removed before
  matching the static Piletilevi series map;
- filters historical performance dates from Piletilevi series pages;
- if a production has no current/future dates (for example Kolemees at the
  moment), the API reports that there are currently no future performances
  instead of treating old dates as usable availability;
- no image logic or modal image presentation changes.
