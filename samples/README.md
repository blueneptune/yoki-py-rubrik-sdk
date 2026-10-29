# Samples

What `rubrik-sample` captured from a real RSC account, in two forms:

| Folder | What | In git? |
|---|---|---|
| `raw/<time>/` | RSC's answers as they came, with real names, plus `mask-map.json` (pseudonym -> original) | **never** - git-ignored |
| `masked/<time>/` | the same answers after `rubrik-mask` | yes - safe to commit and share |

Masked answers keep RSC's shape (field names, statuses, types,
timestamps, UUID and IP formats), so they can be used as test fixtures
for the SDK and for blt.

Before committing a masked capture, read one file of it: the masker
fails rather than leak a value it knows it masked, but only a person can
tell whether something it was told to keep is sensitive after all.
