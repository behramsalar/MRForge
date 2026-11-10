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
