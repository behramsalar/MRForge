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
  radius: "large", // soft, rounded corners everywhere
  scaling: "100%", // 90% denser, 110% roomier
  panelBackground: "solid",
} as const satisfies ThemeProps;

/** Size of the app shell. */
export const shell = { sidebar: "232px", sidebarCollapsed: "64px", topbar: "56px" } as const;

/** Page layout. Values are Radix spacing steps (1 = 4px ... 9 = 64px), never raw pixels. */
export const space = {
  page: "6", // padding around a screen
  section: "5", // gap between blocks
  group: "3", // gap between related controls
  inline: "2", // gap inside a row of small things
} as const;

/** Text sizes (Radix type scale 1-9) used for each role. */
export const type = {
  pageTitle: "7",
  sectionTitle: "5",
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
};

/** Plain-language labels for states (the UI says these, not the internal names). */
export const statusLabel: Record<string, string> = {
  Queued: "Waiting",
  Running: "Running",
  Completed: "Done",
  Failed: "Failed",
  Cancelled: "Cancelled",
  Interrupted: "Stopped early",
};

/** How far a subject is in a stage (dashboard). Same colours as the job states above. */
export const stageColor: Record<string, RadixColor> = {
  none: "gray",
  unavailable: "gray",
  waiting: "gray",
  running: "blue",
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
  partial: "Partly done",
  done: "Done",
  failed: "Failed",
  stopped: "Stopped early",
};
