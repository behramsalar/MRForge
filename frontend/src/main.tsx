import "@radix-ui/themes/styles.css";
import "./theme/forge.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, Suspense, lazy, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { useRoute } from "./lib/router";
import { Dashboard } from "./pages/Dashboard";
import { DesignSystem } from "./pages/DesignSystem";
import { DataPage } from "./pages/DataPage";
import { JobsPage } from "./pages/JobsPage";
import { ProcessPage } from "./pages/ProcessPage";
import { QualityPage } from "./pages/QualityPage";
import { ResultsPage } from "./pages/ResultsPage";
import { SubjectPage } from "./pages/SubjectPage";
import { Settings } from "./pages/Settings";
import { SystemPage } from "./pages/SystemPage";
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

function WorkspacePage({ page, extra, extra2 }: { page: string; extra?: string; extra2?: string }) {
  const { ws, state } = useWorkspace();
  switch (page) {
    case "data":
      return <DataPage ws={ws} extra={extra} state={state} />;
    case "process":
      return <ProcessPage ws={ws} state={state} />;
    case "subject":
      return <SubjectPage ws={ws} label={extra} tab={extra2} state={state} />;
    case "viewer":
      return (
        <Suspense fallback={<p>Loading the viewer…</p>}>
          <ViewerPage ws={ws} subject={extra} image={extra2} />
        </Suspense>
      );
    case "jobs":
      return <JobsPage ws={ws} state={state} />;
    case "quality":
      return <QualityPage ws={ws} />;
    case "results":
      return <ResultsPage ws={ws} tab={extra} />;
    default:
      return <Dashboard ws={ws} state={state} />;
  }
}

function App() {
  const route = useRoute();
  if (route.page === "design") return <DesignSystem />;
  let body: ReactNode;
  if (route.workspace) body = <WorkspacePage page={route.page} extra={route.extra} extra2={route.extra2} />;
  else if (route.page === "settings") body = <Settings />;
  else if (route.page === "system") body = <SystemPage />;
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
