import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api/client";
import { Viewer, type ViewerImage } from "./components/Viewer";

// Spike page for 3b: shows one subject's T1 with the segmentation overlay.
function Spike() {
  const [images, setImages] = useState<ViewerImage[]>([]);
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
  return <Viewer underlay={under} overlays={over} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Spike />
  </StrictMode>,
);
