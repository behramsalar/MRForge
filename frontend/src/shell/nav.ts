import {
  ActivityLogIcon,
  ArchiveIcon,
  BarChartIcon,
  CheckCircledIcon,
  DownloadIcon,
  DesktopIcon,
  EyeOpenIcon,
  GearIcon,
  HomeIcon,
  LayersIcon,
  MixerHorizontalIcon,
} from "@radix-ui/react-icons";
import type { ComponentType, CSSProperties } from "react";

/** A function inside a group (for example Anatomical inside Process); ``id`` is the part of
 * the address after the page name. */
export type NavChild = { id: string; label: string; section?: string }; // section: small heading above this entry

export type NavItem = {
  id: string; // the page name in the address
  label: string;
  icon: ComponentType<{ width?: number; height?: number; style?: CSSProperties }>;
  children?: NavChild[]; // shown as a tree under the item
};

/**
 * The sidebar. Adding a function later (QC, analysis, reports...) is one line here plus its
 * page in main.tsx. Items are shown only if the thing they open exists.
 */
export const WORKSPACE_NAV: NavItem[] = [
  { id: "dashboard", label: "Overview", icon: HomeIcon },
  { id: "import", label: "Import", icon: DownloadIcon },
  { id: "data", label: "Data", icon: ArchiveIcon },
  // One Process page: every stage (preprocessing, analysis, diffusion) is a tile on it.
  { id: "process", label: "Process", icon: MixerHorizontalIcon },
  // Quality: the subjects to check, their reports, and the artifact labelling (tabs on the page).
  { id: "quality", label: "Quality", icon: CheckCircledIcon },
  {
    id: "results",
    label: "Results",
    icon: BarChartIcon,
    children: [
      { id: "connectivity", label: "Connectivity" },
      { id: "diffusion", label: "Diffusion (ALPS)" },
      { id: "methods", label: "Methods and provenance" },
    ],
  },
  { id: "viewer", label: "Viewer", icon: EyeOpenIcon },
  { id: "jobs", label: "Jobs", icon: ActivityLogIcon },
];

/** Pages that are not in the sidebar but are reached from the Process tiles, the subject page and
 * the jump list: the run-one-stage pages with their own results. ``stage`` is the Process tile. */
export const STAGE_PAGES: { stage: string; extra: string; label: string }[] = [
  { stage: "anatomical", extra: "anat", label: "Anatomical" },
  { stage: "functional", extra: "func", label: "Functional preprocessing" },
  { stage: "standard_space", extra: "mni", label: "Standard space" },
  { stage: "connectivity", extra: "conn", label: "Connectivity (ROI to ROI)" },
  { stage: "diffusion", extra: "dwi", label: "Diffusion (ALPS)" },
];

export const GLOBAL_NAV: NavItem[] = [{ id: "workspaces", label: "Workspaces", icon: LayersIcon }];
export const SYSTEM_NAV: NavItem = { id: "system", label: "System", icon: DesktopIcon };
export const SETTINGS_NAV: NavItem = { id: "settings", label: "Settings", icon: GearIcon };

const ALL = [...WORKSPACE_NAV, ...GLOBAL_NAV, SYSTEM_NAV, SETTINGS_NAV];

/** Pages that are reached by clicking something, not from the sidebar. */
const HIDDEN_PAGES: Record<string, string> = { subject: "Subject" };

export function pageLabel(page: string): string {
  return ALL.find((n) => n.id === page)?.label ?? HIDDEN_PAGES[page] ?? page;
}

/** The function shown when a group is opened without naming one. */
export function defaultChild(page: string): string | undefined {
  return ALL.find((n) => n.id === page)?.children?.[0]?.id;
}

/** Top-bar trail for a page: ["Process", "Anatomical"]. */
export function crumbs(page: string, extra?: string): string[] {
  const item = ALL.find((n) => n.id === page);
  const stagePage = page === "process" ? STAGE_PAGES.find((x) => x.extra === extra) : undefined;
  if (stagePage) return [pageLabel(page), stagePage.label];
  const child = item?.children?.find((c) => c.id === (extra ?? defaultChild(page)));
  return [pageLabel(page), ...(child ? [child.label] : [])];
}

/** The sidebar item of a page, for its icon and colour. */
export function navItemFor(page: string): NavItem | undefined {
  return ALL.find((n) => n.id === page);
}
