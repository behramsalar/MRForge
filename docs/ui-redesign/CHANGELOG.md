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

## 2026-11-10 (U1 follow-up: palettes with their own state colours)
- Restored `frontend/dist` from `main` (my U1 build had changed what the user's server on port 8000 shows). See D-17.
- `tokens.ts`: `accentOptions` replaced by `palettes` (accent, gray, state colours) and `paletteCss()`.
- `ThemeProvider.tsx`: `palette` / `setPalette` (browser storage key `mrforge-palette`), injects the palette CSS, sets `data-palette`.
- `DesignSystem.tsx`: palette switcher with a row of state badges and bars to judge each palette.
- Accent-like orange replaced by the accent in `TopBar.tsx` (bell count, avatar), `Workspaces.tsx` ("created by you" badge), `PipelineStepper.tsx` and `LiveProgressDialog.tsx` (progress bars).
- Checked: `tsc` clean, 30 tests pass, indigo palette on the design page and the dashboard at 1280x800. Not yet looked at: teal, blue, neutral, dark mode, other pages.

- Indigo set as the default palette (`ThemeProvider.tsx`, D-18).
- Decision D-19: other palettes and the switcher stay until the user decides.

## 2026-11-10 (U2: shell)
- New `lib/palette.ts` (+ `palette.test.ts`): entries and matching for the jump list.
- New `shell/CommandPalette.tsx`, `shell/ShortcutsDialog.tsx`; `AppShell.tsx` owns their open state and the keys (Cmd/Ctrl+K toggles; `?` opens help unless typing).
- `TopBar.tsx`: "Jump to…" button and a shortcuts button; bell, theme switch and researcher menu unchanged.
- `Sidebar.tsx`: badges on Dashboard and Jobs; resource meter above System/Settings (hidden when the sidebar is collapsed).
- `api/hooks.ts`: `useResources`; `useSubjects` and `useOverview` no longer ask when no workspace is open.
- `shell.css`: styles for the above.
- Checked: `tsc` clean, 33 tests pass (3 new), in the browser: palette opens with Ctrl+K, finds the subject, Enter opens the subject page; shortcuts dialog opens; meter shows "Jobs 0 of 4, Memory 14 / 17 GB". Not checked: badges with real failed/waiting items (scratch workspace has none), Mac Cmd key, collapsed sidebar, other palettes.
