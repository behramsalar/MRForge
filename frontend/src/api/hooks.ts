import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./client";
import { call } from "./call";
import type { WorkspaceState } from "./types";

/**
 * Live state of a workspace (jobs, operations, imports) over server-sent events.
 * The server sends the full state on connect and whenever something changes, so a page that
 * is opened or refreshed mid-job is correct immediately. Data queries are refreshed on change.
 */
export function useWorkspaceState(ws: string): { state: WorkspaceState | null; connected: boolean } {
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [connected, setConnected] = useState(true); // only shown as lost after a drop
  const client = useQueryClient();
  useEffect(() => {
    setState(null);
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    let lastEvent = Date.now();
    let lastData = "";
    const open = () => {
      lastEvent = Date.now();
      source = new EventSource(`/api/workspaces/${encodeURIComponent(ws)}/events`);
      source.onopen = () => setConnected(true);
      source.onerror = () => {
        // The browser gives up on some failures (for example the server restarting behind the
        // dev proxy), so close and reconnect ourselves; the server resends the full state.
        setConnected(false);
        source?.close();
        if (!stopped) retry = setTimeout(open, 2000);
      };
      source.addEventListener("state", (event) => {
        lastEvent = Date.now();
        setConnected(true);
        const data = (event as MessageEvent).data as string;
        if (data === lastData) return; // heartbeat, nothing changed
        lastData = data;
        setState(JSON.parse(data) as WorkspaceState);
        client.invalidateQueries({ queryKey: ["ws", ws] });
      });
    };
    open();
    // The server repeats the state every few seconds; silence means the connection is dead.
    const watchdog = setInterval(() => {
      if (!stopped && Date.now() - lastEvent > 12000) {
        setConnected(false);
        source?.close();
        clearTimeout(retry);
        open();
      }
    }, 3000);
    return () => {
      stopped = true;
      clearInterval(watchdog);
      clearTimeout(retry);
      source?.close();
    };
  }, [ws, client]);
  return { state, connected };
}

export function useWorkspaces() {
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: () => call(api.GET("/api/workspaces")),
  });
}

export function useSubjects(ws: string) {
  return useQuery({
    queryKey: ["ws", ws, "subjects"],
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/subjects", { params: { path: { ws_id: ws } } })),
  });
}

export function useImport(ws: string, id: string | undefined) {
  return useQuery({
    queryKey: ["ws", ws, "import", id],
    enabled: !!id,
    queryFn: () =>
      call(
        api.GET("/api/workspaces/{ws_id}/imports/{import_id}", {
          params: { path: { ws_id: ws, import_id: id! } },
        }),
      ),
  });
}

/** Re-renders every second, so "running for 12 s" counts up between server updates. */
export function useTick(active: boolean): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [active]);
}

export function useOverview(ws: string) {
  return useQuery({
    queryKey: ["ws", ws, "overview"],
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/overview", { params: { path: { ws_id: ws } } })),
  });
}
