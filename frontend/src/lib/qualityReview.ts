import type { Overview, ReportQc, ReportRun } from "../api/types";
import { reviewable } from "./overviewSummary";

type Row = Overview["subjects"][number];

/** The checks that can be compared across subjects, by the name the step gives its QC result.
 * The wording of what to look for is in `qcHelp`. QC only shows; the researcher decides. */
export const CHECKS = [
  { id: "motion", label: "Head movement", match: /^Head motion/ },
  { id: "t1", label: "Alignment to the T1", match: /^Registration to the T1/ },
  { id: "fieldmap", label: "Field map", match: /^Distortion correction/ },
  { id: "standard", label: "Standard space", match: /^Alignment to standard space/ },
] as const;
export type CheckId = (typeof CHECKS)[number]["id"];

export type Show = "todo" | "flagged" | "all";

export const SHOW_FILTER: Record<Show, (r: Row) => boolean> = {
  todo: (r) => reviewable(r) && !r.qc_decision,
  flagged: (r) => !!r.motion_flag || r.qc_decision === "review" || r.stages.some((c) => c.state === "failed" || c.state === "review"),
  all: () => true,
};

type ReportLike = { sections: { runs: ReportRun[] }[] };

/** Every QC result of this check in a subject's report (one per recording, in report order),
 * with the run it came from. */
export function findQc(report: ReportLike | undefined, checkId: CheckId): { run: ReportRun; qc: ReportQc }[] {
  const check = CHECKS.find((c) => c.id === checkId);
  if (!report || !check) return [];
  return report.sections.flatMap((s) => s.runs.flatMap((run) => run.qc.filter((q) => check.match.test(q.name)).map((qc) => ({ run, qc }))));
}

/** The one picture that stands for a QC result in a grid: the joined picture when there is one,
 * otherwise the first kept slice. */
export function thumbnailOf(qc: ReportQc): string | null {
  return qc.image ?? qc.slices[0]?.image ?? null;
}

/** The subject to show after the one at `index` is decided and (maybe) leaves the list: the next
 * one, or the previous when it was the last, or none. */
export function afterDecision(labels: string[], current: string): string | null {
  const i = labels.indexOf(current);
  if (i < 0) return labels[0] ?? null;
  return labels[i + 1] ?? labels[i - 1] ?? null;
}
