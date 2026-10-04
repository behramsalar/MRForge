import { ChevronDownIcon, DoubleArrowLeftIcon, DoubleArrowRightIcon } from "@radix-ui/react-icons";
import { DropdownMenu, Theme } from "@radix-ui/themes";
import { useWorkspaces } from "../api/hooks";
import { href, type Route } from "../lib/router";
import { GLOBAL_NAV, SETTINGS_NAV, WORKSPACE_NAV, type NavItem } from "./nav";

function Item({ item, to, active, collapsed }: { item: NavItem; to: string; active: boolean; collapsed: boolean }) {
  const Icon = item.icon;
  return (
    <a className="nav-item" href={to} aria-current={active ? "page" : undefined} title={collapsed ? item.label : undefined}>
      <Icon width={18} height={18} />
      <span className="nav-label">{item.label}</span>
    </a>
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
            ? WORKSPACE_NAV.map((n) => (
                <Item key={n.id} item={n} to={href(ws, n.id)} active={route.page === n.id} collapsed={collapsed} />
              ))
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
