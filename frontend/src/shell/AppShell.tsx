import { useEffect, useState, type ReactNode } from "react";
import { ActivityPanel } from "../components/ActivityPanel";
import type { Route } from "../lib/router";
import "./shell.css";
import { CommandPalette } from "./CommandPalette";
import { ErrorBoundary } from "./ErrorBoundary";
import { ShortcutsDialog } from "./ShortcutsDialog";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useWorkspace } from "./WorkspaceContext";

const KEY = "mrforge-sidebar-collapsed";

function Banner({ ws }: { ws: string }) {
  const { state } = useWorkspace();
  return <ActivityPanel ws={ws} state={state} />;
}

/** Sidebar, top bar and the content area. Inside a workspace the live banner (running work,
 * the last failure with its buttons) sits at the top of every page. */
export function AppShell({ route, children }: { route: Route; children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(KEY) === "1";
    } catch {
      return false;
    }
  });
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
        return;
      }
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
      if (e.key === "?" && !typing && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setHelpOpen(true);
      }
    };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  }, []);
  const toggle = () => {
    setCollapsed((c) => {
      try {
        localStorage.setItem(KEY, c ? "0" : "1");
      } catch {
        /* not remembered */
      }
      return !c;
    });
  };
  return (
    <div className="shell" data-collapsed={collapsed}>
      <Sidebar route={route} collapsed={collapsed} onToggle={toggle} />
      <div className="main">
        <TopBar route={route} onSearch={() => setPaletteOpen(true)} onHelp={() => setHelpOpen(true)} />
        <main className="content">
          {route.workspace && <Banner ws={route.workspace} />}
          <ErrorBoundary resetKey={`${route.workspace}/${route.page}/${route.extra}`}>{children}</ErrorBoundary>
        </main>
      </div>
      <CommandPalette
        ws={route.workspace}
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onShortcuts={() => setHelpOpen(true)}
      />
      <ShortcutsDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  );
}
