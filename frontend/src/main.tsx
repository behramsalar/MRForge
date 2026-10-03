import "@radix-ui/themes/styles.css";
import { Theme } from "@radix-ui/themes";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api/client";
import { Viewer, type ViewerImage, type ViewerLayout } from "./components/Viewer";
import { DesignSystem } from "./pages/DesignSystem";
import { theme } from "./theme/tokens";

// Temporary pages until the real screens (3e): the viewer spike and the design reference.
function Spike() {
  const [images, setImages] = useState<ViewerImage[]>([]);
  const [layout, setLayout] = useState<ViewerLayout>("row");
  const params = new URLSearchParams(location.search);
  const ws = params.get("ws") ?? "demo";
  const sub = params.get("sub") ?? "sub-001";
  const want = params.get("overlay") ?? "Brain mask";
  useEffect(() => {
    api
      .GET("/api/workspaces/{ws_id}/subjects/{label}/images", {
        params: { path: { ws_id: ws, label: sub } },
      })
      .then((r) => setImages((r.data ?? []) as ViewerImage[]));
  }, [ws, sub]);
  const under = images.find((i) => i.name === "T1, original");
  const over = images.filter((i) => i.name === want);
  if (!under) return <p>Loading…</p>;
  return (
    <>
      <div style={{ padding: 8 }}>
        <button onClick={() => setLayout("grid")} disabled={layout === "grid"}>
          2x2 with 3D
        </button>{" "}
        <button onClick={() => setLayout("row")} disabled={layout === "row"}>
          Three slices in a row
        </button>
      </div>
      <Viewer underlay={under} overlays={over} layout={layout} />
    </>
  );
}

const page = new URLSearchParams(location.search).get("page");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Theme {...theme}>{page === "design" ? <DesignSystem /> : <Spike />}</Theme>
  </StrictMode>,
);
