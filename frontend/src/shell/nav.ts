import {
  ActivityLogIcon,
  ArchiveIcon,
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
  { id: "dashboard", label: "Dashboard", icon: HomeIcon },
  { id: "data", label: "Data", icon: ArchiveIcon },
  // Process is one page with tabs (Pipelines, Single steps), so new pipelines and steps never
  // lengthen the sidebar. Analysis (ROI-to-ROI, diffusion) gets its own item once it exists.
  { id: "process", label: "Process", icon: MixerHorizontalIcon },
  { id: "viewer", label: "Viewer", icon: EyeOpenIcon },
  { id: "jobs", label: "Jobs", icon: ActivityLogIcon },
];

export const GLOBAL_NAV: NavItem[] = [{ id: "workspaces", label: "Workspaces", icon: LayersIcon }];
export const SETTINGS_NAV: NavItem = { id: "settings", label: "Settings", icon: GearIcon };

const ALL = [...WORKSPACE_NAV, ...GLOBAL_NAV, SETTINGS_NAV];

export function pageLabel(page: string): string {
  return ALL.find((n) => n.id === page)?.label ?? page;
}

/** The function shown when a group is opened without naming one. */
export function defaultChild(page: string): string | undefined {
  return ALL.find((n) => n.id === page)?.children?.[0]?.id;
}

/** Top-bar trail for a page: ["Process", "Anatomical"]. */
export function crumbs(page: string, extra?: string): string[] {
  const item = ALL.find((n) => n.id === page);
  const child = item?.children?.find((c) => c.id === (extra ?? defaultChild(page)));
  return [pageLabel(page), ...(child ? [child.label] : [])];
}

/** The sidebar item of a page, for its icon and colour. */
export function navItemFor(page: string): NavItem | undefined {
  return ALL.find((n) => n.id === page);
}
