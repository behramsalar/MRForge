import { Niivue } from "@niivue/niivue";
import { useEffect, useRef } from "react";

export type ViewerImage = {
  url: string;
  name: string;
  role: "underlay" | "overlay";
  colormap?: string | null;
};

/** Embedded NiiVue viewer: one underlay plus any number of overlays. */
export function Viewer({ underlay, overlays }: { underlay: ViewerImage; overlays: ViewerImage[] }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!canvas.current) return;
    const nv = new Niivue({ backColor: [0, 0, 0, 1], show3Dcrosshair: true });
    nv.attachToCanvas(canvas.current);
    nv.loadVolumes([
      { url: underlay.url, name: "underlay.nii.gz", colormap: "gray" },
      ...overlays.map((o, i) => ({
        url: o.url,
        name: `overlay${i}.nii.gz`,
        colormap: o.colormap ?? "red",
        opacity: 0.5,
      })),
    ]);
    return () => {
      nv.volumes = [];
    };
  }, [underlay.url, overlays.map((o) => o.url).join("|")]);

  return <canvas ref={canvas} style={{ width: "100%", height: "70vh", display: "block" }} />;
}
