# UI redesign: decisions

Format: date, decision, reason, status (agreed / proposed / open).

## 2026-11-10 D-01: Work on a separate branch
`ui-redesign`, cut from `main` at `fc3c559`, so `main` is unaffected if the result is not liked. User request. **Agreed.**

## 2026-11-10 D-02: Font (open)
The prototype uses Atkinson Hyperlegible from Google Fonts. The lab computer may be offline and the app has no external requests today. Options: (a) keep the current system font; (b) bundle the font files in the frontend (new npm dependency `@fontsource/...`, works offline). Proposal: (b), after you agree to the dependency. **Open.**

## 2026-11-10 D-03: Rule for the work
The UI never builds shell commands and only talks to the API. Anything needing a backend change is listed in PLAN.md section 3 and asked about first. User instruction. **Agreed.**

## 2026-11-10 D-04: Methods text (open)
The prototype shows a generated methods paragraph with numbered facts. This needs a backend generator and is MVP 2 in CLAUDE.md. Proposal: do not build now; reorganise the existing provenance records only. **Open.**

## 2026-11-10 D-05: Backend-dependent ideas (open)
Cross-subject QC list, live CPU/memory. Proposal: build the frontend first with what exists (lazy per-subject pictures, slots in use), then ask. **Open.**

## 2026-11-10 D-06: Matrix compare and reorder (open)
Computed in the browser from existing data, but CLAUDE.md puts them under "later". Proposal: include only if you say so. **Open.**

## 2026-11-10 D-07: Prototype is a reference, not code
No HTML/CSS/JS is copied from it. Its simulated data and viewer are dropped; the look is reproduced through the existing token files. Reason: a one-file prototype with fake data cannot be merged into a typed React app with a design system. **Proposed.**
