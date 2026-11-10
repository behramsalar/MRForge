# UI redesign: plan (branch `ui-redesign`)

Status: **revised 2026-11-10 after the user's item-by-item comments; waiting for approval of the revised plan.** Nothing in the app has been changed yet.
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
| 1 | Look: warm neutral surfaces, amber = "your move", quiet done state, status colours, Atkinson Hyperlegible font, light/dark | **Adopt the calm, quiet-when-done idea; colours are provisional** (user: not a fan of orange everywhere) | Tokens only, so the palette can be swapped later in one place. Amber is limited to the few things that need the researcher; accent choice stays open (D-08). Font: D-02. |
| 2 | Sidebar: Overview / Process / Quality review / Results / Methods, counts as badges, workspace switcher on top, resource meter and researcher at the bottom | **Adopt the structure and the badges; keep what the prototype dropped** (Data, Jobs, Settings, System, Process sub-pages) | Nav is one file (`shell/nav.ts`). Badges need numbers the API already gives (to confirm in step 0). |
| 3 | Overview: four journey cards (Import, Process, Check quality, Results) with segmented bars | **Adopt** | Pure counting over `/overview` and `/subjects`. Replaces the Dashboard's top. |
| 4 | "Your move": a list of what waits for the researcher (failed step, labels to do, undecided QC) with one button each | **Adopt** | Derivable from subject statuses, failed jobs and "Waiting for you" runs that the UI already shows. Needs checking that nothing needs a new endpoint. |
| 5 | Pipeline map: subject x stage grid, filters, click for details | **Adopt**; this answers a brief question ("100 subjects at a glance") | Per-stage status per subject must come from existing data (to confirm). |
| 6 | Process page: start from the outcome you want ("Connectivity matrices"), route map showing what will run, then pick subjects, then the confirmation dialog | **Adopt; user likes the goal cards and the route map**, as a front for the existing flow | Uses the existing plan / process-batch calls and the stage registry. The confirmation dialog stays the single place that starts work. |
| 7 | Quality review: grid of pictures per check (alignment, head movement, field map, coverage), Undecided / Flagged / All, inspector, keyboard shortcuts, accept/review/exclude with a reason | **Adopt, no extreme rework**, in stages | The decision call exists. The pictures are per subject today; a grid across subjects means many requests (lazy-loaded) or a new list endpoint (ask, D-05). |
| 8 | ICA labelling screen | **Do not adopt** (user did not like it). The existing component-review page stays; it only receives the new look through tokens, plus at most a keyboard shortcut if asked | No layout rework. |
| 9 | Results: matrix with "compare with another subject", order by network, ALPS table, CSV exports | **Adopt the layout (matrix, tables, exports on one page). Compare is not wanted** (no scientific use case; maybe useful for QC later); reorder by network optional | Matrix, exports and tables exist (D-06). |
| 10 | Methods and provenance: a generated methods paragraph with numbered facts, copy button | **Idea approved. Build the provenance half now; the methods text generator comes later** and the page is laid out so it slots in (a reserved "Methods text" area, hidden until it exists) | Needs a backend generator (principle 7; D-04). The per-step record list already exists on the Jobs page and can be reorganised. |
| 11 | Command palette (Cmd/Ctrl+K), keyboard-shortcuts help, activity popover in the top bar | **Adopt** | Frontend only. |
| 12 | Resource meter (CPU/memory bars) in the sidebar | **Partly.** Slots in use and the policy name are available; live CPU/memory bars need a new endpoint | Show what exists; ask before adding live meters (D-05). |
| 13 | Import modal, workspace switcher and researcher switcher as popovers | **Adopt: the import page needs a rework and this approach is to be tried.** Every existing import function stays (folder/zip/tar, NIfTI, BIDS, series table with corrections, convert/organise, validator messages, undo) | Frontend rework of the import screens only. |
| 14 | The prototype's viewer modal (simulated slices) and fake data generators | **Do not adopt** | The real NiiVue viewer stays. All simulated data is dropped. |
| 15 | Mobile menu / phone layout | **Skipped for now** (only use case: checking status remotely from a phone; lowest priority) | Maybe a status-only view much later. |

Open weak spots from the brief that the prototype does not settle (first-time experience, explaining "Waiting for you", provenance readability) are handled through copy and empty states inside the steps below, not new features.

## 1b. Design principle added by the user: density
The mockup is tidier and smaller, with much information readable at a glance on a **13-inch laptop**; the current design is too large and loose. Whatever theme is kept, the new design follows the mockup's density: smaller type scale and spacing, compact tables and cards, more per screen without crowding. Checked at about 1280 x 800 in every step.

## 2. Build order (each step: tests, browser check, changelog, one commit; I stop for your quick check after each)

- **U0 Groundwork (no visible change).** Verify against the running API what data each idea needs; write the result in `DECISIONS.md`. Add a scratch workspace with ~24 fake subjects for checking (outside the repo).
- **U1 Look and density.** Tokens/CSS only: a compact type scale and spacing, radii, status colours, light and dark, a restrained accent (a few palette options shown for you to pick); update `docs/design-system.md` and the `#/design` page.
- **U2 Shell.** Sidebar structure and badges, top bar (search button, activity popover, theme, shortcuts), command palette, shortcuts dialog. All existing routes keep working.
- **U3 Overview.** Journey cards, "Your move", pipeline map; the subject page opens from a row.
- **U4 Process.** Goal cards, route map, subject selection, same confirmation dialog.
- **U5 Quality review.** Grid, inspector, decision flow with keyboard (no extreme rework); cross-subject lists only if you approve a backend change.
- **U5b Import.** New import screens along the mockup's approach with every existing function kept.
- **U6 Component labelling.** No redesign; only checked that the new look fits the existing page.
- **U7 Results and provenance.** Results page (matrix + tables + exports), provenance list with a reserved place for the later methods text. No subject comparison.
- **U8 Polish.** Empty states, error wording, accessibility pass (mobile layout is skipped) (focus, contrast, keyboard), design-system document finalised.
- **Stop point after each step.** After U8: full frontend test run, report, then you decide whether to merge to `main`.

## 3. Ideas that need a backend change (not built; listed with what each needs, so you can judge the effort)
| Idea | What it needs | Rough size (to confirm in U0) |
|---|---|---|
| Fast cross-subject QC grid | One read-only endpoint returning, per subject, the QC picture paths and metrics of a chosen check | Small: reads records the app already writes |
| Live CPU / memory meter | One read-only endpoint (or a field on `/api/resources`) with current usage | Small |
| Generated methods text | A deterministic generator over provenance (MVP 2), plus an endpoint | Medium to large; later |
| "Your move" list and sidebar badges, if the existing endpoints cannot give them | A read-only summary endpoint of what waits for the researcher | Small; only if U0 shows it is needed |
| Subject-by-stage grid, if `/subjects` lacks per-stage status | Add stage status to the subjects list | Small; only if U0 shows it is needed |
| Matrix reorder by network on the server | Not needed; done in the browser | None |

## 4. Risks
- Renaming sidebar entries changes routes (`#/...`); old addresses must keep redirecting so bookmarks, report links and the ICA banner still work.
- The Radix Themes layer and the prototype's hand-written CSS differ; matching the look is done through tokens, not by copying CSS.
- Per-subject picture grids with 100 subjects: must load lazily to stay fast.
