import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { call } from "../api/call";
import type { FullOptions } from "../api/types";

export const STAGE_IDS = ["anatomical", "functional", "artifact_rejection", "standard_space", "connectivity", "diffusion"];

export const DEFAULTS: FullOptions = {
  subject: "",
  stages: {},
  anatomical: { strong_bias: false, subcortical_segmentation: false, resample_to_1mm: false },
  functional: {
    delete_volumes: 5,
    smoothing_fwhm_mm: 5,
    highpass_cutoff_s: 150,
    use_fieldmap: true,
    slice_timing: false,
  },
  artifact: { uncertain_as: "signal", aggressive: false, mode: "manual" },
  connectivity: { atlases: ["schaefer100n7"], only_voxels_with_signal: true },
  diffusion: {
    denoise: true,
    unring: true,
    topup: true,
    second_is_opposite: false,
    eddy: "eddy_cpu",
    eddy_threads: null,
    registration: "linear",
    structural: "none",
    template: "default",
    tensor_method: "flirt",
    roi_source: "default",
    roi_radius_mm: 2.5,
    custom_rois: [],
    round_like_script: false,
  },
};

/** The choices without the subject, in a stable form, to see whether they still equal a preset. */
export function signature(o: Pick<FullOptions, "stages" | "anatomical" | "functional" | "artifact" | "connectivity" | "diffusion">): string {
  const sort = (v: unknown): unknown =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([k, x]) => [k, sort(x)]))
      : v;
  return JSON.stringify(sort({ s: o.stages ?? {}, a: o.anatomical, f: o.functional, r: o.artifact, c: o.connectivity, d: o.diffusion }));
}

/** The groups of stages on the Process page, in the order a methods section describes them. */
export const STAGE_GROUPS: { id: string; title: string; stages: string[] }[] = [
  { id: "pre", title: "Preprocessing", stages: ["anatomical", "functional", "artifact_rejection", "standard_space"] },
  { id: "analysis", title: "Analysis", stages: ["connectivity"] },
  { id: "diffusion", title: "Diffusion", stages: ["diffusion"] },
];

const SETTINGS_KEY: Record<string, keyof FullOptions | undefined> = {
  anatomical: "anatomical",
  functional: "functional",
  artifact_rejection: "artifact",
  connectivity: "connectivity",
  diffusion: "diffusion",
};

/** Whether a stage's settings differ from the defaults (a stage without settings never does). */
export function settingsChanged(stageId: string, opts: FullOptions): boolean {
  const key = SETTINGS_KEY[stageId];
  if (!key) return false;
  const sort = (v: unknown): unknown =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([k, x]) => [k, sort(x)]))
      : v;
  return JSON.stringify(sort(opts[key])) !== JSON.stringify(sort(DEFAULTS[key]));
}

/** The request body for a batch (or one subject): the choices plus who. */
export function planRequests(opts: FullOptions, subjects: string[], preset?: string) {
  const one: FullOptions = { ...opts, subject: subjects[0] ?? "", preset };
  const batch = {
    subjects,
    stages: opts.stages,
    anatomical: opts.anatomical,
    functional: opts.functional,
    artifact: opts.artifact,
    connectivity: opts.connectivity,
    diffusion: opts.diffusion,
    preset,
  };
  return { one, batch };
}

/** What the server would do with these choices for these subjects (one subject: a plan; more: a batch plan). */
export function usePlan(ws: string, opts: FullOptions, subjects: string[], enabled: boolean, preset?: string) {
  const { one, batch } = planRequests(opts, subjects, preset);
  const many = subjects.length > 1;
  return useQuery({
    queryKey: ["ws", ws, "plan", many ? JSON.stringify(batch) : JSON.stringify(one)],
    enabled: enabled && subjects.length > 0,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      if (many) {
        const b = await call(api.POST("/api/workspaces/{ws_id}/process/plan-batch", { params: { path: { ws_id: ws } }, body: batch }));
        return { stages: b.stages, can_start: b.runnable > 0, steps: 0, batch: b };
      }
      const p = await call(api.POST("/api/workspaces/{ws_id}/process/plan", { params: { path: { ws_id: ws } }, body: one }));
      return { ...p, batch: null };
    },
  });
}

/** Put one stage's settings back to the defaults. */
export function resetStage(stageId: string, opts: FullOptions): FullOptions {
  const key = SETTINGS_KEY[stageId];
  return key ? ({ ...opts, [key]: DEFAULTS[key] } as FullOptions) : opts;
}

/** Dialog stage id -> the id the overview uses for the same stage. */
export const OVERVIEW_ID: Record<string, string> = {
  anatomical: "anatomical",
  functional: "preprocessing",
  artifact_rejection: "artifact_rejection",
  standard_space: "standard_space",
  connectivity: "connectivity",
  diffusion: "diffusion",
};

type Row = { stages: { id: string; state: string }[] };

/** How many of these subjects already have the stage done, and how many cannot run it, from the overview. */
export function stageCounts(stageId: string, rows: Row[]) {
  const states = rows.map((r) => r.stages.find((c) => c.id === OVERVIEW_ID[stageId])?.state ?? "none");
  const n = (s: string) => states.filter((x) => x === s).length;
  return { done: n("done"), unavailable: n("unavailable"), total: rows.length };
}
