# MRForge design system (Stage 4 overhaul)

Component library: **Radix Themes** (no Tailwind). Look: **Forge**, a charcoal sidebar (dark in
both light and dark mode) and an amber accent. Light, dark or "follow my computer" is the
user's choice (Settings or the top bar); the choice is remembered in the browser.
The app is used on a desktop or laptop screen; phone and tablet layouts are not a goal.

## Where things live
| What | File |
|---|---|
| Colours by meaning, spacing steps, text sizes, state labels | `frontend/src/theme/tokens.ts` |
| Amber accent and sidebar colours (CSS variables) | `frontend/src/theme/forge.css` |
| Shell: sidebar, top bar, theme, researcher profile, error boundary | `frontend/src/shell/` |
| Sidebar items (one line per function; groups use `children`) | `frontend/src/shell/nav.ts` |
| Reusable pieces | `frontend/src/components/ui/` (`Layout`: `PageHeader`, `EmptyState`, `StatCard`; `Badges`) |
| Live reference page | `#/design` in the running app |

## Page anatomy
Every page: `PageHeader` (title + one plain sentence), then cards. The page title is the only
`h1`; section titles are `h2` (`Heading as="h2"`). Content width is capped
(`layout.contentWidth`) so lines stay readable on wide screens.

## Rules
1. Use Radix Themes components; do not write a new one if one exists.
2. No hard-coded colours, fonts or pixel sizes in screens. Spacing is a Radix step
   (`space.page`, `space.section`, `space.group`, `space.inline`), text a Radix size
   (`type.body`, `type.help`, ...). Layout-only flex sizes (a minimum column width) are fine.
3. Colours are chosen by meaning and never reused for something else: green done / High
   confidence, amber waiting for you / Medium, red failed / Low, orange stopped early,
   grey skipped or not applicable. Use `statusColor`, `stageColor`, `confidenceColor`,
   `actionColor`.
4. Plain-language copy. "Stopped early", not "Interrupted"; "Needs your input", not "ask";
   steps are named by what they do (`stepName` in `JobsPanel.tsx`), not by the tool.
5. Advanced options are collapsed. Only offer actions whose inputs exist; when an action is
   unavailable, show it disabled with the reason, or explain with an `EmptyState`.
6. Every empty page invites the next action (`EmptyState` with a button or link).
7. Every error uses `ErrorCallout`: what happened, why, what to do next, and "View log"
   where there is one. A network failure ("could not reach MRForge") is only used when the
   server really cannot be reached; a refused value names the value (`INVALID_VALUE`).
8. Long work shows live progress (`LiveProgressDialog`): which step runs, what it is doing,
   elapsed time. FSL gives no percentage, so progress counts steps, not time.
9. Anything that changes data asks for confirmation first and states what will happen
   (`ConfirmProcessDialog`, `UndoImportDialog`).
10. Keyboard: everything reachable by Tab, visible focus ring (Radix default), buttons and
    links have text or an `aria-label`.
11. Adding a function: one line in `nav.ts`, its page in `main.tsx`; for processing, a stage
    in `backend/mrforge/processing.py` (it then appears in the full-processing dialog).

## Not used
Tailwind CSS is not installed (see `docs/DECISIONS.md`): Radix layout props cover layout, and
a second styling system is how one-off styles creep in.
