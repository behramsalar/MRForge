# UI redesign: plan (branch `ui-redesign`)

Status: **proposed, waiting for the user's approval.** Nothing in the app has been changed yet.
Sources: `~/Documents/uiworkshop/app-overview-for-ui-ideas.md` (the brief) and `~/Documents/uiworkshop/mrforge-prototype.html` (the mockup; simulated data, one file, no real API).
Change log: `CHANGELOG.md` in this folder. Decisions: `DECISIONS.md` in this folder.

## Ground rules (from the user and CLAUDE.md)
1. Work only on branch `ui-redesign`, cut from `main` (2026-11-10). `main` is untouched until the user accepts the result.
2. The UI never builds shell commands and only talks to the API. The engine, steps, provenance and API stay as they are.
3. If an idea needs a backend or API change: **stop and ask first.** Such ideas are listed in section 3 and are not built until the user says so.
4. Nothing that works today may stop working. Every existing page and action keeps a home (the prototype leaves out Data, Jobs, Settings, System, single-step pages, the subject page, Workspaces and the real viewer; those are restyled, not removed).
5. Components and tokens stay in the design system (`frontend/src/theme/`, Radix Themes); no one-off styles. Plain-language copy; flag, don't decide (principle 6).
6. Every change is written to `CHANGELOG.md`, every choice to `DECISIONS.md`. Frontend tests, `tsc` and a build run after each step; checked in the browser against a scratch workspace, never the user's real data.

## 1. What the prototype contains, and what I think of each part

| # | Prototype part | Verdict | Why |
|---|---|---|---|
| 1 | Look: warm neutral surfaces, amber = "your move", quiet done state, status colours, Atkinson Hyperlegible font, light/dark | **Adopt**, mapped onto the existing tokens | Tokens and Forge theme already exist; this is a token/CSS change. Font needs a decision (D-02). |
| 2 | Sidebar: Overview / Process / Quality review / Results / Methods, counts as badges, workspace switcher on top, resource meter and researcher at the bottom | **Adopt the structure and the badges; keep what the prototype dropped** (Data, Jobs, Settings, System, Process sub-pages) | Nav is one file (`shell/nav.ts`). Badges need numbers the API already gives (to confirm in step 0). |
| 3 | Overview: four journey cards (Import, Process, Check quality, Results) with segmented bars | **Adopt** | Pure counting over `/overview` and `/subjects`. Replaces the Dashboard's top. |
| 4 | "Your move": a list of what waits for the researcher (failed step, labels to do, undecided QC) with one button each | **Adopt** | Derivable from subject statuses, failed jobs and "Waiting for you" runs that the UI already shows. Needs checking that nothing needs a new endpoint. |
| 5 | Pipeline map: subject x stage grid, filters, click for details | **Adopt**; this answers a brief question ("100 subjects at a glance") | Per-stage status per subject must come from existing data (to confirm). |
| 6 | Process page: start from the outcome you want ("Connectivity matrices"), route map showing what will run, then pick subjects, then the confirmation dialog | **Adopt as a front for the existing flow** | Uses the existing plan / process-batch calls and the stage registry. The confirmation dialog stays the single place that starts work. |
| 7 | Quality review: grid of pictures per check (alignment, head movement, field map, coverage), Undecided / Flagged / All, inspector, keyboard shortcuts, accept/review/exclude with a reason | **Adopt**, in stages | The decision call exists. The pictures are per subject today; a grid across subjects means many requests (lazy-loaded) or a new list endpoint (ask, D-05). |
| 8 | ICA labelling screen: rows with map, time course, spectrum, one-key Signal/Noise/Unsure, AROMA suggestions, bulk "use AROMA's confident labels" | **Adopt as a redesign of the existing component-review page** | Same data and same save call. Bulk-accept only pre-fills; the researcher still saves (principle 6). |
| 9 | Results: matrix with "compare with another subject", order by network, ALPS table, CSV exports | **Adopt the layout; compare and reorder later** | Matrix, exports and tables exist. Compare / reorder are computed in the browser from two existing matrix calls, but CLAUDE.md lists them under "later", so they wait for approval (D-06). |
| 10 | Methods and provenance: a generated methods paragraph with numbered facts, copy button | **Adopt only the provenance half now.** The generated methods text is **not** built | Deterministic methods text is MVP 2 and needs a backend generator (principle 7). Not done without approval (D-04). The per-step record list (settings, commands, Copy command) already exists on the Jobs page and can be reorganised. |
| 11 | Command palette (Cmd/Ctrl+K), keyboard-shortcuts help, activity popover in the top bar | **Adopt** | Frontend only. |
| 12 | Resource meter (CPU/memory bars) in the sidebar | **Partly.** Slots in use and the policy name are available; live CPU/memory bars need a new endpoint | Show what exists; ask before adding live meters (D-05). |
| 13 | Import modal, workspace switcher and researcher switcher as popovers | **Adopt the idea, keep the real import flow** (folder picker, series table, undo) | Restyle only. |
| 14 | The prototype's viewer modal (simulated slices) and fake data generators | **Do not adopt** | The real NiiVue viewer stays. All simulated data is dropped. |
| 15 | Mobile menu / phone layout | **Adopt lightly** (the shell collapses on narrow screens) | The lab uses desktops; low priority. |

Open weak spots from the brief that the prototype does not settle (first-time experience, explaining "Waiting for you", provenance readability) are handled through copy and empty states inside the steps below, not new features.

## 2. Build order (each step: tests, browser check, changelog, one commit; I stop for your quick check after each)

- **U0 Groundwork (no visible change).** Verify against the running API what data each idea needs; write the result in `DECISIONS.md`. Add a scratch workspace with ~24 fake subjects for checking (outside the repo).
- **U1 Look.** Tokens/CSS only: palette, radii, type scale, status colours, light and dark; update `docs/design-system.md` and the `#/design` page.
- **U2 Shell.** Sidebar structure and badges, top bar (search button, activity popover, theme, shortcuts), command palette, shortcuts dialog. All existing routes keep working.
- **U3 Overview.** Journey cards, "Your move", pipeline map; the subject page opens from a row.
- **U4 Process.** Outcome-first start, route map, subject selection, same confirmation dialog.
- **U5 Quality review.** Grid, inspector, decision flow with keyboard; later, the cross-subject lists if you approve a backend change.
- **U6 Component labelling.** Row layout and shortcuts on the existing review page.
- **U7 Results and provenance.** Results page (matrix + tables + exports), provenance list; compare / reorder only if approved.
- **U8 Polish.** Empty states, error wording, narrow screens, accessibility pass (focus, contrast, keyboard), design-system document finalised.
- **Stop point after each step.** After U8: full frontend test run, report, then you decide whether to merge to `main`.

## 3. Ideas that need a backend change (not built; I ask first)
1. A cross-subject list of QC pictures and metrics (for a fast Quality grid).
2. Live CPU and memory usage for the sidebar meter.
3. A generated methods paragraph from provenance (MVP 2 in CLAUDE.md).
4. Anything else found in U0 that the existing endpoints cannot give (for example a ready-made "needs you" list).

## 4. Risks
- Renaming sidebar entries changes routes (`#/...`); old addresses must keep redirecting so bookmarks, report links and the ICA banner still work.
- The Radix Themes layer and the prototype's hand-written CSS differ; matching the look is done through tokens, not by copying CSS.
- Per-subject picture grids with 100 subjects: must load lazily to stay fast.
