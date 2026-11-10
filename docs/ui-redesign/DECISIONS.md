# UI redesign: decisions

Format: date, decision, reason, status (agreed / proposed / open).

## 2026-11-10 D-01: Work on a separate branch
`ui-redesign`, cut from `main` at `fc3c559`, so `main` is unaffected if the result is not liked. User request. **Agreed.**

## 2026-11-10 D-02: Font (open)
The prototype uses Atkinson Hyperlegible from Google Fonts. The lab computer may be offline and the app has no external requests today. Options: (a) keep the current system font; (b) bundle the font files in the frontend (new npm dependency `@fontsource/...`, works offline). Proposal: (b), after you agree to the dependency. Until answered the system font stays (U1 changes no font). **Open.**

## 2026-11-10 D-03: Rule for the work
The UI never builds shell commands and only talks to the API. Anything needing a backend change is listed in PLAN.md section 3 and asked about first. User instruction. **Agreed.**

## 2026-11-10 D-04: Methods text (open)
The prototype shows a generated methods paragraph with numbered facts. This needs a backend generator and is MVP 2 in CLAUDE.md. User: idea approved, generator later. Decision: build the provenance half now and reserve a place for the methods text; generator is a later backend task. **Agreed.**

## 2026-11-10 D-05: Backend-dependent ideas (open)
Cross-subject QC list, live CPU/memory. User: fine for now; list what each needs so the effort can be judged (PLAN.md section 3). Decision: frontend first with what exists. **Agreed.**

## 2026-11-10 D-06: Matrix compare and reorder (open)
Computed in the browser from existing data, but CLAUDE.md puts them under "later". User: compare has no scientific use case, not a priority (maybe for QC later). Decision: no subject comparison; reorder by network optional. **Agreed.**

## 2026-11-10 D-07: Prototype is a reference, not code
No HTML/CSS/JS is copied from it. Its simulated data and viewer are dropped; the look is reproduced through the existing token files. Reason: a one-file prototype with fake data cannot be merged into a typed React app with a design system. **Proposed.**

## 2026-11-10 D-08: Colours are provisional, accent restrained
User is not a fan of orange everywhere. Decision: keep all colours in the token files so the palette can change in one place; use the accent only where the researcher has to act; offer a few palette options in U1 for the user to choose. **Agreed.**

## 2026-11-10 D-09: Density (user)
Mockup is tidier and smaller and shows more at a glance on a 13-inch laptop; the current design is too large. Decision: compact type and spacing, checked at about 1280 x 800 in every step. **Agreed.**

## 2026-11-10 D-10: ICA labelling screen stays as it is
User did not like the mockup's version and finds the original good enough. Decision: no layout rework (plan part 8, U6). **Agreed.**

## 2026-11-10 D-11: Import page is reworked, functions kept
Try the mockup's approach; keep every existing import function. New step U5b. **Agreed.**

## 2026-11-10 D-12: Mobile layout skipped
Only use case is remote status checks from a phone. **Agreed.**

## 2026-11-10 D-13: How density is done (U1)
Radix `scaling` 100% -> 90% (smaller type, spacing and controls everywhere in one place), radius `large` -> `medium`, page padding step 6 -> 4, section gap 5 -> 4, page title size 7 -> 6, section title 5 -> 4, sidebar 232 -> 208 px (collapsed 64 -> 56), top bar 56 -> 44 px. Reason: user wants more at a glance on a 13-inch laptop; one global knob keeps every existing screen consistent without editing each. Values can be tuned in `tokens.ts` / `shell.css`. **Proposed (user to judge by eye).**

## 2026-11-10 D-14: Provisional accent switcher (superseded by D-16)
`ThemeProvider` takes the accent from a browser-stored choice (default: the earlier amber); the choice is made on `#/design` (Palette). When the user picks one, it moves into `tokens.ts` and the switcher is removed. Options shown: Forge amber, indigo, teal, blue, neutral. **Proposed.**

## 2026-11-10 D-15: Dev setup for checks
`vite.config.ts` reads `MRFORGE_API` (default unchanged) so the dev UI can talk to a scratch server instead of the user's server on port 8000. `.claude/launch.json` (local, not committed) starts the scratch server (port 8100, scratch copy of the `nifti` workspace) and the dev UI (port 5180). The user's workspaces are never written to. **Agreed by the rule in D-03 / scope.**

## 2026-11-10 D-16: Palettes carry their own state colours (user feedback)
Problem: with the indigo accent the done (green), failed (red) and running (blue) colours and some hard-coded orange (researcher avatar, bell count, "created by" badge, in-progress bars) clashed. Decision: a palette is an accent plus its own colours for the five state meanings. Screens keep saying green / amber / red / blue / orange by meaning; `tokens.ts` (`palettes`, `paletteCss`) re-points those names per palette with CSS variables, so no screen needs changing per palette. Accent-like uses of orange (avatar, bell count, "created by you", in-progress bars) now use the accent. "Forge amber" has no re-pointing and is identical to the earlier look; "neutral" keeps the standard state colours. Indigo: done teal, failed ruby, running cyan; Teal: grass / tomato / indigo; Blue: jade / ruby / cyan. All provisional. **Proposed.**

## 2026-11-10 D-17: The original must stay untouched (user, "really important")
`main` and the user's running app on port 8000 must keep working and looking as before. My earlier U1 build overwrote `frontend/dist`, which that server serves, so the app on 8000 briefly showed the new look. Fixed: `frontend/dist` was rebuilt from `main`. From now on: **never run `npm run build` on this branch**; checks use the dev server (port 5180, scratch data, port 8100) only; a build of this branch happens only at the end, into a separate folder, if the user asks. **Agreed.**

## 2026-11-10 D-18: Indigo is the palette to continue with (user)
Indigo (teal done, ruby failed, cyan running) is the default on this branch. The other palettes and the switcher stay on `#/design` until the user confirms the indicator colours, then they are removed and indigo is written into `theme` in `tokens.ts`. **Agreed (indicator colours still to be confirmed).**

## 2026-11-10 D-19: Other palettes stay for now (user)
The user is not fully sure about indigo yet. Decision: keep the palette switcher and all palettes on `#/design`, indigo as the default, and do not remove anything until the user says so. **Agreed.**

## 2026-11-10 D-20: What U2 includes, and what it leaves for later steps
Built: sidebar badges (Dashboard: failed + waiting-for-you count, red when something failed, else amber; Jobs: running now), a small resource meter at the sidebar foot (jobs in use out of the limit, memory in use, from the existing `/api/resources`), a "Jump to…" button in the top bar and the Cmd/Ctrl+K palette (pages, every function under a page, subjects, a few actions), a keyboard-shortcuts dialog (`?` key or the top-bar button; lists only shortcuts that exist). **Not changed:** the sidebar entries and their names. The prototype's Overview / Quality review / Results / Methods entries do not exist as pages yet, so they arrive with U3, U5 and U7 (an entry is added only when its page exists). The bell/activity popover is kept as it is. Memory shown is "in use of total" (total minus available); CPU load is not shown (needs a backend change, see PLAN section 3). **Agreed by plan; wording of the meter is a proposal.**

## 2026-11-10 D-21: The Overview (U3): what replaced what
The Dashboard page (route id stays `dashboard`; the sidebar and top bar now say **Overview**) is rebuilt from the same overview data, no backend change:
- **Journey cards** (Import, Process, Check quality, Results) replace the five number cards and the "Processing pipeline" stepper. Their numbers: Import = subjects imported (+ imports that need an answer); Process = one group per subject (finished / running / waiting for you / failed or stopped / not started or partly done); Check quality = decided among subjects whose functional preprocessing is done, excluded counted separately; Results = complete subjects not excluded. All counted in `lib/overviewSummary.ts` (tested); nothing is decided there (principle 6).
- **Your move** replaces the amber "Needs your review" banner: failures and interrupted work first (red), then component labelling, then undecided quality decisions, each with its own button. Same information as before, plus failures and quality, which the dashboard only showed as counts.
- **Pipeline map** (subject x stage cells, search, the same filters as before, click opens the subject page) replaces the Subjects table *on this page*. `SubjectsTable` stays unchanged for every other page. Not on the map any more: the written "head motion" numbers (shown as a "motion" flag only; numbers are on the subject page) and the last-activity column (now a tooltip on the row). **Open: say if you want either back as a column.**
- Kept as they were: Running now, Recent activity, the analysis-ready card, the empty "start your first import" state.
- Sidebar fix found while testing at 1280 x 800: with the Process tree open, System, Settings and Collapse were pushed off the bottom; the function list now scrolls instead.
- Page-header icon box 48 -> 36 px (density, D-09). `PipelineStepper` and `StatCard` are no longer used on any page; left in place for now (removal is part of the polish step).
**Proposed (user to judge by eye).**

## 2026-11-10 D-22: How big lists were checked without a big workspace
The scratch workspace has one subject. A throw-away dev server config (`frontend/vite.mock.config.mjs`, excluded from git through `.git/info/exclude`) answers `/overview` with 24 invented subjects in all states and passes everything else to the scratch server. Nothing is written anywhere. **Agreed (scope of D-15).**
