import { MULTIPLANAR_TYPE, Niivue, SHOW_RENDER, SLICE_TYPE } from "@niivue/niivue";
import { useEffect, useRef, useState } from "react";

export type ViewerImage = {
  url: string;
  name: string;
  role: "underlay" | "overlay";
  colormap?: string | null;
};

/** "grid": 2x2 with the 3D view. "row": the three slices in one line, no 3D view. */
export type ViewerLayout = "grid" | "row";

function applyLayout(nv: Niivue, layout: ViewerLayout) {
  nv.setSliceType(SLICE_TYPE.MULTIPLANAR);
  nv.opts.multiplanarShowRender = layout === "grid" ? SHOW_RENDER.ALWAYS : SHOW_RENDER.NEVER;
  nv.setMultiplanarLayout(layout === "grid" ? MULTIPLANAR_TYPE.GRID : MULTIPLANAR_TYPE.ROW);
}

/** Embedded NiiVue viewer: one underlay plus any number of overlays. */
export function Viewer({
  underlay,
  overlays,
  layout = "row",
}: {
  underlay: ViewerImage;
  overlays: ViewerImage[];
  layout?: ViewerLayout;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const viewer = useRef<Niivue | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!canvas.current) return;
    const nv = new Niivue({ backColor: [0, 0, 0, 1], show3Dcrosshair: true });
    viewer.current = nv;
    nv.attachToCanvas(canvas.current);
    nv.loadVolumes([
      { url: underlay.url, name: "underlay.nii.gz", colormap: "gray" },
      ...overlays.map((o, i) => ({
        url: o.url,
        name: `overlay${i}.nii.gz`,
        colormap: o.colormap ?? "red",
        opacity: 0.5,
      })),
    ]).then(() => setReady(true));
    return () => {
      setReady(false);
      viewer.current = null;
      nv.volumes = [];
    };
  }, [underlay.url, overlays.map((o) => o.url).join("|")]);

  // Changing the layout re-arranges the loaded images; nothing is reloaded.
  useEffect(() => {
    if (viewer.current && ready) applyLayout(viewer.current, layout);
  }, [layout, ready]);

  // NiiVue sizes its canvas to the parent element, so the parent carries the height.
  return (
    <div style={{ width: "100%", height: "75vh", position: "relative" }}>
      <canvas ref={canvas} style={{ display: "block" }} />
    </div>
  );
}
