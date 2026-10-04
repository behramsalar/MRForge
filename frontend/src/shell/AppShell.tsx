import { useState, type ReactNode } from "react";
import { ActivityPanel } from "../components/ActivityPanel";
import type { Route } from "../lib/router";
import "./shell.css";
import { ErrorBoundary } from "./ErrorBoundary";
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
        <TopBar route={route} />
        <main className="content">
          {route.workspace && <Banner ws={route.workspace} />}
          <ErrorBoundary resetKey={`${route.workspace}/${route.page}/${route.extra}`}>{children}</ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
