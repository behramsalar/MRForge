import { ChevronDownIcon, ChevronRightIcon, DoubleArrowLeftIcon, DoubleArrowRightIcon } from "@radix-ui/react-icons";
import { DropdownMenu, Theme } from "@radix-ui/themes";
import { Fragment, useEffect, useState } from "react";
import { useWorkspaces } from "../api/hooks";
import { areaColor } from "../theme/tokens";
import { href, type Route } from "../lib/router";
import { GLOBAL_NAV, SETTINGS_NAV, WORKSPACE_NAV, defaultChild, type NavItem } from "./nav";

function Item({ item, to, active, collapsed }: { item: NavItem; to: string; active: boolean; collapsed: boolean }) {
  const Icon = item.icon;
  return (
    <a className="nav-item" href={to} aria-current={active ? "page" : undefined} title={collapsed ? item.label : undefined}>
      <Icon width={18} height={18} style={{ color: `var(--${areaColor[item.id] ?? "gray"}-9)` }} />
      <span className="nav-label">{item.label}</span>
    </a>
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
        <Icon width={18} height={18} style={{ color: `var(--${areaColor[item.id] ?? "gray"}-9)` }} />
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
        <Icon width={18} height={18} style={{ color: `var(--${areaColor[item.id] ?? "gray"}-9)` }} />
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
                  <Item key={n.id} item={n} to={href(ws, n.id)} active={route.page === n.id} collapsed={collapsed} />
                ),
              )
            : GLOBAL_NAV.map((n) => (
                <Item key={n.id} item={n} to="#/" active={route.page === n.id} collapsed={collapsed} />
              ))}
        </nav>

        <div className="sidebar-foot">
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
