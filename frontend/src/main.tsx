import "@radix-ui/themes/styles.css";
import { Theme } from "@radix-ui/themes";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { WorkspaceLayout } from "./components/WorkspaceLayout";
import { useRoute } from "./lib/router";
import { AnatomicalPage } from "./pages/AnatomicalPage";
import { DesignSystem } from "./pages/DesignSystem";
import { FunctionalPage } from "./pages/FunctionalPage";
import { ImportPage } from "./pages/ImportPage";
import { Workspaces } from "./pages/Workspaces";
import { theme } from "./theme/tokens";

// The viewer (NiiVue) is big, so it is only downloaded when someone opens it.
const ViewerPage = lazy(() => import("./pages/ViewerPage").then((m) => ({ default: m.ViewerPage })));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: true, staleTime: 2000 } },
});

function App() {
  const route = useRoute();
  if (route.page === "design") return <DesignSystem />;
  const ws = route.workspace;
  if (!ws) return <Workspaces />;
  return (
    <WorkspaceLayout ws={ws} page={route.page}>
      {(state) =>
        route.page === "anat" ? (
          <AnatomicalPage ws={ws} state={state} />
        ) : route.page === "func" ? (
          <FunctionalPage ws={ws} state={state} />
        ) : route.page === "view" ? (
          <Suspense fallback={<p>Loading the viewer…</p>}>
            <ViewerPage ws={ws} subject={route.extra} />
          </Suspense>
        ) : (
          <ImportPage ws={ws} importId={route.extra} state={state} />
        )
      }
    </WorkspaceLayout>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Theme {...theme}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </Theme>
  </StrictMode>,
);
