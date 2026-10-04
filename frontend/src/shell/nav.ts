import {
  ActivityLogIcon,
  ArchiveIcon,
  EyeOpenIcon,
  GearIcon,
  HomeIcon,
  LayersIcon,
  MixerHorizontalIcon,
} from "@radix-ui/react-icons";
import type { ComponentType } from "react";

export type NavItem = {
  id: string; // the page name in the address
  label: string;
  icon: ComponentType<{ width?: number; height?: number }>;
};

/**
 * The sidebar. Adding a function later (QC, analysis, reports...) is one line here plus its
 * page in main.tsx. Items are shown only if the thing they open exists.
 */
export const WORKSPACE_NAV: NavItem[] = [
  { id: "dashboard", label: "Dashboard", icon: HomeIcon },
  { id: "data", label: "Data", icon: ArchiveIcon },
  { id: "process", label: "Process", icon: MixerHorizontalIcon },
  { id: "viewer", label: "Viewer", icon: EyeOpenIcon },
  { id: "jobs", label: "Jobs", icon: ActivityLogIcon },
];

export const GLOBAL_NAV: NavItem[] = [{ id: "workspaces", label: "Workspaces", icon: LayersIcon }];
export const SETTINGS_NAV: NavItem = { id: "settings", label: "Settings", icon: GearIcon };

export function pageLabel(page: string): string {
  const all = [...WORKSPACE_NAV, ...GLOBAL_NAV, SETTINGS_NAV];
  return all.find((n) => n.id === page)?.label ?? page;
}
