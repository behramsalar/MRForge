import { ChevronDownIcon, ChevronRightIcon, DoubleArrowLeftIcon, DoubleArrowRightIcon } from "@radix-ui/react-icons";
import { DropdownMenu, Theme } from "@radix-ui/themes";
import { Fragment, useEffect, useState } from "react";
import { useOverview, useResources, useWorkspaces } from "../api/hooks";
import { href, type Route } from "../lib/router";
import { GLOBAL_NAV, SETTINGS_NAV, SYSTEM_NAV, WORKSPACE_NAV, defaultChild, type NavItem } from "./nav";

type Badge = { n: number; tone: "red" | "amber" | "blue"; title: string };

function Item({
  item,
  to,
  active,
  collapsed,
  badge,
}: {
  item: NavItem;
  to: string;
  active: boolean;
  collapsed: boolean;
  badge?: Badge;
}) {
  const Icon = item.icon;
  return (
    <a className="nav-item" href={to} aria-current={active ? "page" : undefined} title={collapsed ? item.label : undefined}>
      <Icon width={18} height={18} />
      <span className="nav-label">{item.label}</span>
      {badge && badge.n > 0 && !collapsed && (
        <span className="nav-badge" data-tone={badge.tone} title={badge.title}>
          {badge.n}
        </span>
      )}
    </a>
  );
}

/** What the computer is doing, in two short lines (slots in use, free memory). */
function ResourceMeter() {
  const info = useResources();
  const d = info.data;
  if (!d) return null;
  const slots = `${Math.min(d.machine.jobs_running, d.policy.max_subjects)} of ${d.policy.max_subjects}`;
  const used = Math.max(0, d.machine.ram_gb - d.machine.free_ram_gb);
  return (
    <div className="side-meter" title="Processing slots in use, and memory in use on this computer">
      <div>
        <span>Jobs</span>
        <b>{slots}</b>
      </div>
      <div>
        <span>Memory</span>
        <b>
          {used.toFixed(0)} / {d.machine.ram_gb.toFixed(0)} GB
        </b>
      </div>
      <span className="meter" aria-hidden="true">
        <i style={{ width: `${Math.min(100, (100 * used) / d.machine.ram_gb)}%` }} />
      </span>
    </div>
  );
}

const OPEN_KEY = "mrforge-nav-open";

function readOpen(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(OPEN_KEY) ?? "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

/** An item with functions under it, shown as a tree: Process > Anatomical, Functional. */
function Group({ item, ws, route, collapsed }: { item: NavItem; ws: string; route: Route; collapsed: boolean }) {
  const Icon = item.icon;
  const here = route.page === item.id;
  const current = route.extra ?? defaultChild(item.id);
  const [open, setOpen] = useState(() => readOpen().includes(item.id));
  const shown = open; // opens by itself when you arrive here; you can still fold it
  useEffect(() => {
    if (here && !open) setOpen(true);
  }, [here]); // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = () => {
    const next = !shown;
    setOpen(next);
    try {
      const rest = readOpen().filter((x) => x !== item.id);
      localStorage.setItem(OPEN_KEY, JSON.stringify(next ? [...rest, item.id] : rest));
    } catch {
      /* not remembered */
    }
  };
  const first = defaultChild(item.id);
  if (collapsed) {
    return (
      <a className="nav-item" href={href(ws, item.id, first)} aria-current={here ? "page" : undefined} title={item.label}>
        <Icon width={18} height={18} />
      </a>
    );
  }
  return (
    <div className="nav-tree">
      <button
        className="nav-item nav-group"
        data-here={here}
        aria-expanded={shown}
        onClick={() => {
          // Opening a closed group also goes to its first function; clicking an open one folds it.
          if (!here) {
            location.hash = href(ws, item.id, first);
            if (!shown) toggle();
          } else toggle();
        }}
      >
        <Icon width={18} height={18} />
        <span className="nav-label">{item.label}</span>
        <ChevronRightIcon className="nav-chevron" data-open={shown} />
      </button>
      {shown && (
        <div className="nav-children">
          {item.children?.map((c) => (
            <Fragment key={c.id}>
              {c.section && <div className="nav-section">{c.section}</div>}
              <a
                className="nav-child"
                href={href(ws, item.id, c.id)}
                aria-current={here && current === c.id ? "page" : undefined}
              >
                {c.label}
              </a>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  );
}

/** The dark sidebar: workspace switcher, the functions of the open workspace, settings. */
export function Sidebar({
  route,
  collapsed,
  onToggle,
}: {
  route: Route;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const workspaces = useWorkspaces();
  const ws = route.workspace;
  const overview = useOverview(ws ?? "");
  const o = overview.data;
  // Badges say how many things want the researcher (red: something failed) or are running now.
  const badges: Record<string, Badge> = {};
  if (o) {
    const needs = (o.failed ?? 0) + (o.needs_review ?? 0);
    badges.dashboard = {
      n: needs,
      tone: o.failed ? "red" : "amber",
      title: `${o.failed} failed, ${o.needs_review} waiting for you`,
    };
    badges.jobs = { n: o.running, tone: "blue", title: `${o.running} running now` };
  }
  return (
    <Theme asChild appearance="dark" hasBackground={false}>
      <aside className="sidebar" aria-label="Main">
        <a className="brand" href="#/" title="All workspaces">
          <span className="brand-mark" aria-hidden="true">
            M
          </span>
          <span className="brand-text">MRForge</span>
        </a>

        {ws && (
          <DropdownMenu.Root>
            <DropdownMenu.Trigger>
              <button className="ws-switch" aria-label="Switch workspace">
                <span>{ws}</span>
                <ChevronDownIcon />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Content>
              {(workspaces.data ?? []).map((w) => (
                <DropdownMenu.Item key={w.id} onSelect={() => (location.hash = href(w.id, "dashboard"))}>
                  {w.name}
                </DropdownMenu.Item>
              ))}
              <DropdownMenu.Separator />
              <DropdownMenu.Item onSelect={() => (location.hash = "#/")}>All workspaces</DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        )}

        <nav className="nav nav-grow" aria-label="Functions">
          {ws
            ? WORKSPACE_NAV.map((n) =>
                n.children ? (
                  <Group key={n.id} item={n} ws={ws} route={route} collapsed={collapsed} />
                ) : (
                  <Item
                    key={n.id}
                    item={n}
                    to={href(ws, n.id)}
                    active={route.page === n.id}
                    collapsed={collapsed}
                    badge={badges[n.id]}
                  />
                ),
              )
            : GLOBAL_NAV.map((n) => (
                <Item key={n.id} item={n} to="#/" active={route.page === n.id} collapsed={collapsed} />
              ))}
        </nav>

        {!collapsed && <ResourceMeter />}
        <div className="sidebar-foot">
          <Item item={SYSTEM_NAV} to="#/system" active={route.page === "system"} collapsed={collapsed} />
          <Item item={SETTINGS_NAV} to="#/settings" active={route.page === "settings"} collapsed={collapsed} />
          <button className="nav-item" onClick={onToggle} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
            {collapsed ? <DoubleArrowRightIcon width={18} height={18} /> : <DoubleArrowLeftIcon width={18} height={18} />}
            <span className="nav-label">Collapse</span>
          </button>
        </div>
      </aside>
    </Theme>
  );
}
