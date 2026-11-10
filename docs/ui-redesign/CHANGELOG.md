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

## 2026-11-10 (stage tiles: alignment and look, user request)
- Tiles are taller (about 130 px) with centred text, a larger name and a round check mark top left (filled when included, dashed when the stage is impossible); the gear stays top right.
- Alignment: the group heading and its help text now sit in a fixed-height block, and the two groups in the Analysis / Diffusion row stretch to equal height, so both tiles start at the same line (checked: same top and height in the browser).
- Files: `components/StageTile.tsx`, `components/overview.css`, `pages/FullProcessingPage.tsx`. Checked: `tsc` clean. Tests not re-run (no logic changed). Not checked: narrow widths, light mode, other palettes.

## 2026-11-10 (stage tiles: description on top, parameters below, user request)
- Tile layout is now fixed: stage name, the stage's own description (up to four lines, never changes when the tile is selected), then at the bottom a small itemised list of its settings (name left, value right, up to six rows, a long value wraps to two lines). A tile that is off keeps its list, dimmed. An impossible stage shows its reason in place of the description.
- Tiles are taller (about 230 px) so the description and the list fit without jumping.
- Files: `components/StageTile.tsx` (props `description`, `params` replace `summary`), `components/overview.css`, `pages/FullProcessingPage.tsx` (`paramsOf` lists the plan's settings once each).
- Checked: `tsc` clean; browser at 1280x800: selecting Artifact rejection leaves every description unchanged and only the values in the lists change (Standard space and Connectivity: "denoised data"); all tiles in a row are the same height. Not checked: narrow widths, light mode, other palettes, the 24-subject mock.

## 2026-11-10 (tile corners; interim sidebar, option A)
- Tile corners rounded a little more (`--radius-4`).
- Sidebar is now: Overview, Data, Process, Quality, Results (Connectivity, Diffusion (ALPS)), Viewer, Jobs; System, Settings and the resource meter unchanged below. The Process tree (Pipelines, Anatomical, Preprocessing, Artifact rejection, Standard space, Connectivity, Diffusion) is gone: every stage is a tile on the one Process page.
- New `pages/ResultsPage.tsx` (the connectivity file index and matrix view, and the ALPS table, moved unchanged from the old single-step pages) and `pages/QualityPage.tsx` (for now the existing artifact-labelling screen; the cross-subject check list comes with U5).
- `lib/router.ts`: old addresses still work. `process/anat|func|mni|full` and `anat`, `func`, `anatomical` open Process; `process/conn` opens Results > Connectivity; `process/dwi` Results > Diffusion; `process/ica` opens Quality. Links inside the app (bell, banners, Overview, subject page) now point at the new pages.
- Removed pages no longer reachable: `AnatomicalPage`, `FunctionalPage`, `StagePage`, `QcPanel` (their running function is the Process page; their pictures are in each subject's Results tab). `ProcessPage` is now just the Process page. Subject page: the "Open the page" buttons of the anatomical, functional and standard-space cards are gone (nothing to open); connectivity, diffusion and artifact cards open the new pages.
- Tests updated (nav, router, palette) with new cases for the redirects. Checked: `tsc` clean, 42 tests pass; browser at 1280x800: `process/anat` opens Process, `process/ica` and `quality` open the labelling page with Quality highlighted, `results/connectivity` and `results/diffusion` open with their entries highlighted. Not checked: the Results pages with real data (scratch has no connectivity matrices), clicking every redirect from inside the app, the 24-subject mock, collapsed sidebar, light mode.
- Deviation from option A: the first entry stays "Data" (not "Import"), because that page also holds the subjects and files tabs; "Reports" is not a Results entry yet (reports are per subject, on the subject page).

## 2026-11-10 (user feedback on the interim sidebar: keep the stage pages, split Import and Data, fuller Quality)
- The single-step pages are back (restored from git, unchanged): Anatomical, Functional preprocessing, Standard space, Connectivity (with its results), Diffusion (with its results). They are not in the sidebar. They are reached from a small arrow icon on each Process tile, from the cards on the subject page ("Open the page"), and from the jump list (Ctrl/Cmd+K, hint "Run one stage"). Their addresses (`process/anat`, `func`, `mni`, `conn`, `dwi`) work again; the top-bar trail reads Process / <page>.
- Import and Data are two pages and two sidebar entries. Import: the imports (scan, series table, convert, validate, undo). Data: the subjects and files. Old `data/<import-id>` and `import/...` addresses open Import.
- Quality is a page with two tabs. "Subjects and reports": every subject with its functional state, head motion, artifact-rejection state and quality decision, filter Needs a decision / Flagged / All, and per subject a Report button (the subject's results tab) and a Decide button (the subject page, where the decision is recorded). "Artifact rejection": the existing labelling screen, header folded into the page. `process/ica` and all in-app links to the review open the second tab.
- Results (Connectivity, Diffusion) stay in the sidebar as before; their pages also still exist under Process.
- New: `pages/ImportPage.tsx`, `components/QualityTable.tsx`; changed: `DataPage`, `QualityPage`, `StageTile` (page link), `nav.ts` (`STAGE_PAGES`), `router.ts`, `palette.ts`, `SubjectPage`, `ComponentReviewPage` (`embedded`).
- Checked: `tsc` clean, 42 tests pass (router, nav and palette tests updated). Browser at 1280x800: every address above opens the right page with the right trail; Quality shows 9 undecided / 5 flagged / 24 in the 24-subject mock; the tile arrows point at the right pages. Not checked: Report and Decide buttons clicked through, the Import page with a live import, light mode, collapsed sidebar.

## 2026-11-10 (U5: quality review)
- Quality > "Subjects and reports" is now the review. Choose who (Needs a decision / Flagged / All), and how: **Pictures** (one picture per subject for a chosen check: Head movement, Alignment to the T1, Field map, Standard space; pictures load only when they scroll into view) or **List** (the table of the earlier step). Clicking a tile or a "Decide" button opens the **inspector**.
- Inspector: the pictures of the chosen check large, the metrics of that run, warnings, the help text for what to look for, Previous / Next with "3 of 9", Accept / Mark for review / Exclude with a required reason (quick reasons as before; Enter saves, Esc cancels the reason first), Full report and Open interactively links. After a decision it moves on to the next subject. Keys: ← → or k j, A R X, 1 to 4; listed in the shortcuts dialog (`?`).
- New: `lib/qualityReview.ts` (+ test, 4 cases: checks found by name, thumbnail choice, who comes next), `components/QualityGrid.tsx`, `QualityInspector.tsx`, `QualityReview.tsx`; `QualityTable.tsx` lost its own filter; `QualityDecisionCard.tsx` exports `QUICK_REASONS`; `ShortcutsDialog.tsx` lists the review keys; styles in `overview.css`.
- No backend change: each tile asks for that subject's existing report when it scrolls into view (cached for a minute and reused by the inspector). Many subjects mean many requests, one per visible tile.
- Checked: `tsc` clean, 46 tests pass. Browser at 1280x800 with the 24-subject mock (which now also answers invented reports and pictures; scratch only): the grid shows 9 pictures for "Needs a decision" and 24 for All; the inspector opens, arrow keys move between subjects, X shows the reason box, Esc cancels the reason without closing the dialog, 3 switches the check; on the real scratch subject sub-001 a decision entered by keyboard (A, typed reason, Enter) was recorded by the server and the inspector moved on. That test left an "accept" decision on sub-001 in the scratch workspace (scratch only). Not checked: real functional QC pictures (the scratch workspace only has diffusion pictures), 100+ subjects, light mode, other palettes, the Field map check on data that has no field map.

## U5b Import page
- Header with Import scans button; step strip; sticky import bar ("Convert and organise"); list hidden for a single import. Files: pages/data/ImportsTab.tsx, pages/ImportPage.tsx.

## U6 ICA screen
- Checked under Quality > Artifact rejection: header, subject picker, run button and the empty state fit the new look. The labelling screen itself is unchanged (original kept, as agreed). Not seen with real components: the scratch workspace has no MELODIC run, so the labelling view must be checked on a real dataset.

## U7 Results and provenance
- New Results > Methods and provenance (components/ProvenanceView.tsx, pages/ResultsPage.tsx, shell/nav.ts + test). Checked on the scratch workspace: runs, versions, commands listed.

## U8 Polish
- Removed unused PipelineStepper and StatCard; design-system.md updated with the redesign patterns. Final check: types, 46 tests, build (to a temp folder only; see D-17).
