import { IconButton } from "@radix-ui/themes";
import { MinusIcon, PlusIcon, ResetIcon } from "@radix-ui/react-icons";
import { MULTIPLANAR_TYPE, Niivue, SHOW_RENDER, SLICE_TYPE } from "@niivue/niivue";
import { useEffect, useRef, useState } from "react";

export type ViewerLayer = {
  url: string;
  colormap?: string | null;
  opacity: number; // 0 to 1
};

/** "row": the three slices in one line. "grid": 2x2 with the 3D view. */
export type ViewerLayout = "grid" | "row";

function applyLayout(nv: Niivue, layout: ViewerLayout) {
  nv.setSliceType(SLICE_TYPE.MULTIPLANAR);
  nv.opts.multiplanarShowRender = layout === "grid" ? SHOW_RENDER.ALWAYS : SHOW_RENDER.NEVER;
  nv.setMultiplanarLayout(layout === "grid" ? MULTIPLANAR_TYPE.GRID : MULTIPLANAR_TYPE.ROW);
}

/**
 * Embedded NiiVue viewer: one image plus any number of overlays. Changing opacity, the
 * volume of a time series or the layout never reloads the images; changing which images are
 * shown does.
 */
export function Viewer({
  underlay,
  overlays,
  layout = "row",
  frame = 0,
  height = "70vh",
  onLoaded,
  onError,
}: {
  underlay: string;
  overlays: ViewerLayer[];
  layout?: ViewerLayout;
  frame?: number; // volume of a time series (0 = first)
  height?: string;
  onLoaded?: (volumes: number) => void;
  onError?: (message: string) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const viewer = useRef<Niivue | null>(null);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const key = [underlay, ...overlays.map((o) => `${o.url}|${o.colormap ?? ""}`)].join("\n");
  const onLoadedRef = useRef(onLoaded);
  const onErrorRef = useRef(onError);
  onLoadedRef.current = onLoaded;
  onErrorRef.current = onError;
  const latest = useRef(overlays);
  latest.current = overlays;

  useEffect(() => {
    if (!canvas.current) return;
    let cancelled = false;
    setLoading(true);
    setReady(false);
    const nv = new Niivue({ backColor: [0, 0, 0, 1], show3Dcrosshair: true });
    viewer.current = nv;
    nv.attachToCanvas(canvas.current);
    nv.loadVolumes([
      { url: underlay, name: "image.nii.gz", colormap: "gray" },
      ...latest.current.map((o, i) => ({
        url: o.url,
        name: `overlay${i}.nii.gz`,
        colormap: o.colormap ?? "red",
        opacity: o.opacity,
      })),
    ])
      .then(() => {
        if (cancelled) return;
        setReady(true);
        setLoading(false);
        onLoadedRef.current?.(nv.volumes[0]?.nFrame4D ?? 1);
      })
      .catch(() => {
        if (cancelled) return;
        setLoading(false);
        onErrorRef.current?.("The image could not be opened.");
      });
    return () => {
      cancelled = true;
      setReady(false);
      viewer.current = null;
      nv.volumes = [];
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (viewer.current && ready) applyLayout(viewer.current, layout);
  }, [layout, ready]);

  // Opacity changes apply to the loaded overlays without reloading anything.
  useEffect(() => {
    const nv = viewer.current;
    if (!nv || !ready) return;
    // The list of overlays can change a moment before their images finish loading.
    overlays.forEach((o, i) => {
      if (i + 1 < nv.volumes.length) nv.setOpacity(i + 1, o.opacity);
    });
  }, [overlays.map((o) => o.opacity).join(","), ready]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const nv = viewer.current;
    const vol = nv?.volumes[0];
    if (nv && vol && ready && (vol.nFrame4D ?? 1) > 1) nv.setFrame4D(vol.id, frame);
  }, [frame, ready]);

  // Zoom buttons: the mouse wheel stays "next slice", as people expect in a viewer.
  const zoomBy = (factor: number | null) => {
    const nv = viewer.current;
    if (!nv) return;
    const [x, y, z, zoom] = nv.scene.pan2Dxyzmm;
    const next = factor === null ? 1 : Math.min(8, Math.max(1, zoom * factor));
    nv.setPan2Dxyzmm(factor === null || next === 1 ? [0, 0, 0, 1] : [x, y, z, next]);
  };

  // NiiVue sizes its canvas to the parent element, so the parent carries the height.
  return (
    <div style={{ width: "100%", height, position: "relative", background: "black", borderRadius: "var(--radius-3)" }}>
      <canvas ref={canvas} style={{ display: "block" }} />
      {ready && (
        <div style={{ position: "absolute", top: "var(--space-2)", right: "var(--space-2)", display: "flex", gap: "var(--space-1)" }}>
          <IconButton size="1" variant="solid" color="gray" highContrast aria-label="Zoom in" title="Zoom in (the mouse wheel still scrolls through slices)" onClick={() => zoomBy(1.25)}>
            <PlusIcon />
          </IconButton>
          <IconButton size="1" variant="solid" color="gray" highContrast aria-label="Zoom out" title="Zoom out" onClick={() => zoomBy(0.8)}>
            <MinusIcon />
          </IconButton>
          <IconButton size="1" variant="solid" color="gray" highContrast aria-label="Reset zoom" title="Reset zoom" onClick={() => zoomBy(null)}>
            <ResetIcon />
          </IconButton>
        </div>
      )}
      {loading && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "grid",
            placeItems: "center",
            color: "white",
            fontSize: "var(--font-size-3)",
            pointerEvents: "none",
          }}
        >
          Loading the image…
        </div>
      )}
    </div>
  );
}
