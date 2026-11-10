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

## 2026-11-10 (U3: Overview)
- New `lib/overviewSummary.ts` (+ test, 4 cases): process groups, quality counts, "Your move" items.
- New `components/OverviewCards.tsx`, `YourMove.tsx`, `PipelineMap.tsx`, `overview.css`.
- `pages/Dashboard.tsx` rebuilt on them; `shell/nav.ts`: label "Dashboard" -> "Overview" (route unchanged, old links work).
- `components/SubjectsTable.tsx`: exports `FILTERS` and `Filter` (no behaviour change). `components/ui/Layout.tsx`: smaller page-header icon.
- `shell/shell.css`: function list scrolls so System/Settings stay visible.
- Checked: `tsc` clean, 37 tests pass; in the browser at 1280x800 with 24 invented subjects (all states) and with the real one-subject scratch workspace; indigo palette, dark mode. Not checked: light mode and other palettes on this screen, a real failure, clicking through "Your move" buttons, the empty workspace screen, 100+ subjects.

## 2026-11-10 (U3 follow-up, user request)
- "Your move" renamed "Needs your decision" (`components/YourMove.tsx`, comments in `overview.css`, `lib/overviewSummary.ts`).
- "Recent activity" moved from the left column to the bottom of the right column, below the pipeline map and the analysis-ready card (`pages/Dashboard.tsx`), so it ranks lower.
- Checked: `tsc` clean; in the browser (24 invented subjects) heading order is Needs your decision, Running now, Pipeline map, Recent activity. Tests not re-run.

## 2026-11-10 (U4: Process)
- New `lib/goals.ts` (+ test, 3 cases): the goals (Full processing, Clean the scans, Analysis-ready in standard space, Connectivity matrices, Diffusion) as sets of existing stage ids.
- New `components/RouteMap.tsx` + styles in `overview.css`: the stages of the chosen goal in order, optional artifact rejection drawn dashed, and for the ticked subjects "Done earlier" / "Will run" / "Not possible".
- `pages/FullProcessingPage.tsx` (the Pipelines page): "1. What do you want?" goal cards, a switch for optional artifact rejection, the route map, "2. Which subjects?" (the existing table, unchanged). The single-subject card, batch bar and Jobs panel are kept.
- `components/ConfirmProcessDialog.tsx`: new optional prop `stagesOn` (stages ticked when it opens). Everything else in the dialog is unchanged; it stays the one place that starts work and shows the real plan.
- Checked: `tsc` clean, 40 tests pass. Browser at 1280x800: 24 invented subjects (route map shows done/will-run per subject) and the real scratch subject (dialog opens with the goal's stages ticked: Connectivity goal -> Anatomical, Functional, Standard space, Connectivity). Nothing was started. Not checked: batch dialog with several subjects, artifact-rejection switch end to end, light mode, other palettes.

## 2026-11-10 (U4 rework: Process workbench, after the user's review)
- User feedback on the first U4: settings hidden behind the start button, no preset saving visible, start bar only for 2+ subjects, single steps cannot batch, rows too tall, sidebar grouping unclear. Goal cards dropped (presets take their job).
- Removed `lib/goals.ts` (+ test) and `components/RouteMap.tsx` (and their CSS); removed the first U4's `stagesOn` use (the prop stays on the dialog, unused by the page).
- New `lib/processOptions.ts` (+ test, 5 cases): defaults, stage groups (Preprocessing / Analysis / Diffusion), `settingsChanged`, `resetStage`, `stageCounts`, `usePlan`, request builders. Moved out of `ConfirmProcessDialog.tsx`.
- New `components/StageSettings.tsx`: the five stages' settings controls, moved unchanged out of the dialog (the dialog now uses it, so they are written once).
- New `PresetBar.tsx` (choose / "Changed" / Update / Save as new / Undo / Delete), `StageRow.tsx`, `StageSettingsPanel.tsx` (side panel with Reset to defaults), `ReviewStartDialog.tsx` (summary only).
- `pages/FullProcessingPage.tsx` rewritten as the Process page: preset bar, three stage groups with one-line summaries and a Settings button each, subjects, a start bar that shows as soon as one subject is ticked.
- `SubjectsTable.tsx`: compact rows (Radix size 1, tighter padding, short date, motion on one line): 64 -> 42 px per row on the 24-subject check. `lib/labels.ts`: `whenShort`.
- Checked: `tsc` clean, 41 tests pass. Browser at 1280x800 on the real scratch subject: summaries come from the plan, Functional panel changes smoothing and the card then shows "Changed" and a dot, Artifact rejection panel shows the three modes, Connectivity panel shows the atlases, the review dialog lists what will and will not run (4 steps). Nothing was started and no preset was saved (presets live in the shared app config, not the scratch workspace). Not checked: saving / updating / deleting a preset, a batch of several subjects (the invented subjects are unknown to the scratch server), light mode, other palettes.
- Not done yet: sidebar option A and removing the single-step pages (they still exist at their old addresses). Reason: A's Quality and Results entries need the U5 and U7 pages, and the connectivity / diffusion result views still live on the single-step pages.

## 2026-11-10 (Process page: stage tiles, user request)
- User did not like the line-by-line toggles; chose layout A (selectable tiles).
- New `components/StageTile.tsx` replaces `StageRow.tsx` (removed): a tile is a button that includes / leaves out the stage (filled in the accent colour = included), with a gear for its settings (dot when changed), a short summary (up to four settings, three lines) and a "Done earlier" badge once subjects are ticked; an impossible stage is greyed with the reason.
- `pages/FullProcessingPage.tsx`: Preprocessing tiles in one row with arrows in running order; Analysis and Diffusion side by side below. Styles in `components/overview.css`.
- Settings panel, preset bar, subject list, start bar and review dialog unchanged.
- Checked: `tsc` clean, 41 tests pass; browser at 1280x800 on the real scratch subject: clicking Artifact rejection fills it and changes the summaries (Standard space and Connectivity then say "denoised data") and the preset bar shows "Changed"; a ticked subject shows "Done earlier" on Diffusion and the start bar. Not checked: the settings gear after this change (panel itself unchanged), narrow widths, light mode, other palettes.
