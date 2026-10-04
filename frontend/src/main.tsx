import "@radix-ui/themes/styles.css";
import "./theme/forge.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, Suspense, lazy, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { useRoute } from "./lib/router";
import { AnatomicalPage } from "./pages/AnatomicalPage";
import { Dashboard } from "./pages/Dashboard";
import { DesignSystem } from "./pages/DesignSystem";
import { ImportPage } from "./pages/ImportPage";
import { JobsPage } from "./pages/JobsPage";
import { ProcessPage } from "./pages/ProcessPage";
import { Settings } from "./pages/Settings";
import { Workspaces } from "./pages/Workspaces";
import { AppShell } from "./shell/AppShell";
import { ResearcherProvider } from "./shell/ResearcherProvider";
import { ThemeProvider } from "./shell/ThemeProvider";
import { WorkspaceProvider, useWorkspace } from "./shell/WorkspaceContext";

// The viewer (NiiVue) is big, so it is only downloaded when someone opens it.
const ViewerPage = lazy(() => import("./pages/ViewerPage").then((m) => ({ default: m.ViewerPage })));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: true, staleTime: 2000 } },
});

function WorkspacePage({ page, extra }: { page: string; extra?: string }) {
  const { ws, state } = useWorkspace();
  switch (page) {
    case "data":
      return <ImportPage ws={ws} importId={extra} state={state} />;
    case "process":
      return <ProcessPage ws={ws} tab={extra} state={state} />;
    case "viewer":
      return (
        <Suspense fallback={<p>Loading the viewer…</p>}>
          <ViewerPage ws={ws} subject={extra} />
        </Suspense>
      );
    case "jobs":
      return <JobsPage ws={ws} state={state} />;
    case "anatomical":
      return <AnatomicalPage ws={ws} state={state} />;
    default:
      return <Dashboard ws={ws} state={state} />;
  }
}

function App() {
  const route = useRoute();
  if (route.page === "design") return <DesignSystem />;
  let body: ReactNode;
  if (route.workspace) body = <WorkspacePage page={route.page} extra={route.extra} />;
  else if (route.page === "settings") body = <Settings />;
  else body = <Workspaces />;
  const shell = <AppShell route={route}>{body}</AppShell>;
  return route.workspace ? <WorkspaceProvider ws={route.workspace}>{shell}</WorkspaceProvider> : shell;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <ResearcherProvider>
          <App />
        </ResearcherProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
