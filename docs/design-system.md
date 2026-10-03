# MRForge design system

Component library: **Radix Themes 3.3** (chosen by the user, 2026-10-03). Look: soft, rounded,
calm; indigo accent on a slate grey, light appearance.

## Where things live
| What | File |
|---|---|
| All tokens (theme, spacing, text sizes, colour meanings, state labels) | `frontend/src/theme/tokens.ts` |
| Reusable pieces | `frontend/src/components/ui/` (badges now; more as screens need them) |
| Live reference of everything | `http://localhost:5173/?page=design` |

## Rules
1. Use Radix Themes components (`Button`, `Table`, `Card`, `Callout`, `Dialog`, ...). Do not
   write a new component if one exists.
2. No hard-coded colours, pixel sizes or fonts in screens. Spacing is a Radix step
   (`space.page`, `space.section`, ...), text is a Radix size (`type.body`, ...), colours are
   chosen by meaning (`statusColor`, `confidenceColor`, `actionColor`).
3. The same word always has the same colour: High confidence is green, Medium amber, Low red;
   "Needs your input" is solid amber; failed is red; stopped early is orange.
4. Plain-language copy. The UI says "Stopped early", not "Interrupted"; "Needs your input", not
   "ask". Labels for engine states are in `statusLabel`.
5. Advanced options are collapsed by default; only offer actions whose inputs exist (disable
   with a short reason, do not hide silently).
6. Every error shows what happened, why, and what to do next (`ErrorBody` from the API), with
   "View log" one click away.
7. Change the look in `tokens.ts` only (for example `accentColor`, `radius`, `scaling`).

## Not used
Tailwind CSS (named in CLAUDE.md section 3) is not installed: Radix Themes' layout props
(`Flex`, `Grid`, `Box`, spacing steps) cover layout, and mixing a second styling system is how
one-off styles creep in. Proposed to the user for approval; see DECISIONS.md.
