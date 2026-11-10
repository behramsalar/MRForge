/**
 * Design tokens: the ONE place that decides how MRForge looks.
 * Components take colours, radii and sizes from here (or from Radix Themes' own scales);
 * nothing else in the app may hard-code a colour, pixel size or font.
 * Rules and rationale: docs/design-system.md
 */
import type { ThemeProps } from "@radix-ui/themes";

type RadixColor = NonNullable<ThemeProps["accentColor"]>;

/**
 * Global look, passed to <Theme>. Light or dark comes from ThemeProvider (the user's switch).
 * The accent is "Forge amber": Radix orange, tuned in theme/forge.css, which also holds the
 * charcoal sidebar colours. Tokens.ts and forge.css together are the one place for the look.
 */
export const theme = {
  accentColor: "orange",
  grayColor: "gray",
  radius: "medium", // slightly tighter corners (UI redesign, D-09)
  scaling: "90%", // denser: more on screen on a 13-inch laptop (UI redesign, D-09)
  panelBackground: "solid",
} as const satisfies ThemeProps;

/**
 * Accent colour options while the palette is still being chosen (UI redesign, D-08).
 * The choice is remembered in the browser; once one is picked it becomes `theme.accentColor`
 * and this list goes away. "orange" is the Forge amber of the earlier design.
 */
export const accentOptions = [
  { id: "orange", label: "Forge amber (earlier look)" },
  { id: "indigo", label: "Indigo" },
  { id: "teal", label: "Teal" },
  { id: "blue", label: "Blue" },
  { id: "gray", label: "Neutral (no colour accent)" },
] as const satisfies readonly { id: RadixColor; label: string }[];
export type AccentId = (typeof accentOptions)[number]["id"];

/** Size of the app shell. */
export const shell = { sidebar: "208px", sidebarCollapsed: "56px", topbar: "44px" } as const;

/** Page layout. Values are Radix spacing steps (1 = 4px ... 9 = 64px), never raw pixels. */
export const space = {
  page: "4", // padding around a screen
  section: "4", // gap between blocks
  group: "3", // gap between related controls
  inline: "2", // gap inside a row of small things
} as const;

/** Text sizes (Radix type scale 1-9) used for each role. */
export const type = {
  pageTitle: "6",
  sectionTitle: "4",
  body: "3",
  help: "2", // explanations, hints
  caption: "1",
} as const;

/** Max width of reading content, so lines stay short and calm. */
export const layout = { contentWidth: "1400px", narrowWidth: "640px" } as const;

/** Colour meaning. The same word always has the same colour everywhere. */
export const confidenceColor: Record<"High" | "Medium" | "Low", RadixColor> = {
  High: "green",
  Medium: "amber",
  Low: "red",
};

/** What the importer will do with a series. */
export const actionColor: Record<"import" | "skip" | "ask", RadixColor> = {
  import: "green",
  skip: "gray",
  ask: "amber", // needs the researcher's decision
};

/** Job and operation states (same names as the engine). */
export const statusColor: Record<string, RadixColor> = {
  Queued: "gray",
  Running: "blue",
  Completed: "green",
  Failed: "red",
  Cancelled: "gray",
  Interrupted: "orange",
  Waiting: "amber", // needs the researcher
};

/** Plain-language labels for states (the UI says these, not the internal names). */
export const statusLabel: Record<string, string> = {
  Queued: "Waiting",
  Running: "Running",
  Completed: "Done",
  Failed: "Failed",
  Cancelled: "Cancelled",
  Interrupted: "Stopped early",
  Waiting: "Waiting for you",
};

/** How far a subject is in a stage (dashboard). Same colours as the job states above. */
export const stageColor: Record<string, RadixColor> = {
  none: "gray",
  unavailable: "gray",
  waiting: "gray",
  running: "blue",
  review: "amber",
  partial: "amber",
  done: "green",
  failed: "red",
  stopped: "orange",
};

export const stageLabel: Record<string, string> = {
  none: "Not started",
  unavailable: "Not possible",
  waiting: "Waiting",
  running: "Running",
  review: "Needs you",
  partial: "Partly done",
  done: "Done",
  failed: "Failed",
  stopped: "Stopped early",
};

/**
 * One accent (Forge amber) for everything interactive or decorative; green / amber / red /
 * orange / blue / gray only ever mean a state. No per-area colours: they fought the accent.
 */

/**
 * Colour scale of the connectivity matrices: a data scale, not a state. Blue is a negative
 * value, white zero, red a positive value; the diagonal and missing values are drawn neutral.
 * The range is fixed per statistic so two matrices can be compared by eye.
 */
export const matrixScale = {
  negative: [33, 102, 172],
  zero: [247, 247, 247],
  positive: [178, 24, 43],
  diagonal: [200, 200, 200],
  missing: [225, 225, 225],
  boundary: "rgba(0, 0, 0, 0.45)",
  flag: "rgba(0, 0, 0, 0.35)", // hatching of regions with little signal
  range: { r: 1, z: 2 }, // REVIEW(domain): symmetric limits of the colour scale
} as const;
