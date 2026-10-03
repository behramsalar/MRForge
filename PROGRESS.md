# Progress

**Current stage:** 0 (Foundations), branch `stage-0-foundations`

| Sub-step | Status |
|---|---|
| 0a Repo scaffold | done |
| 0b `scripts/check_env.py` | done |
| 0c `docs/architecture.md` | done (draft; user review pending) |
| 0d DECISIONS / TEST_DATA / PROGRESS | done |
| CLAUDE.md update (`mriapp` -> `mrforge`, section 0 facts) | waiting for user approval of diff |

## Known issues
- Non-login shells do not load `FSLDIR` (set in `~/.zprofile`). Handled in design by configurable FSL lookup (see DECISIONS).
- `bids-validator` is only on PATH when nvm's Node is loaded.
- Test data is full-size DICOM (1.2 GB), possibly with identifying info; not suitable for fast unit tests.

## Open questions
- Lab members for UX feedback (blank; needed only from Stage 3/4).
- Fieldmap types the lab's scanner produces (needed before Stage 5c).
- Public test datasets to record in `docs/TEST_DATA.md`.

## Next action
User reviews `docs/architecture.md` and the stage-end checklist; then says "stage accepted".
