# UI redesign: change log

Every change on branch `ui-redesign` is listed here with its commit.

## 2026-11-10
- Branch `ui-redesign` created from `main` (`fc3c559`).
- Added `docs/ui-redesign/PLAN.md`, `DECISIONS.md`, `CHANGELOG.md`. No application code changed.
- Plan revised after the user's item-by-item comments: colours provisional (D-08), density as a principle (D-09), ICA screen unchanged (D-10), import rework added as U5b (D-11), compare dropped, mobile skipped (D-12), backend-needs table added.

## 2026-11-10 (U0 and U1)
- U0: added `U0-findings.md` (what the API gives; memory and slots need no backend change after all).
- U1 `frontend/src/theme/tokens.ts`: Radix scaling 90%, radius medium, smaller spacing and title steps, narrower sidebar and top bar; `accentOptions` list.
- U1 `frontend/src/shell/shell.css`: sidebar 208/56 px, top bar 44 px, content padding and gap one step smaller.
- U1 `frontend/src/shell/ThemeProvider.tsx`: provisional accent choice (`accent`, `setAccent`, remembered in the browser).
- U1 `frontend/src/pages/DesignSystem.tsx`: "Palette (provisional)" switcher.
- `frontend/vite.config.ts`: `MRFORGE_API` environment variable for the dev proxy.
- Checked: `tsc` clean, 30 frontend tests pass, dashboard looked at in the browser at 1280x800 with amber, teal and indigo, light and dark. Not checked: other pages with the new density, the production build.
