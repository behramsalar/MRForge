import type { Overview } from "../api/types";

type Row = Overview["subjects"][number];

/** Counting for the Overview cards and the "Needs your decision" list. Pure: everything comes from the
 * overview the server already gives, nothing is decided here (flag, don't decide). */
export type Segment = { key: "done" | "running" | "waiting" | "failed" | "rest"; n: number };

const stage = (r: Row, id: string) => r.stages.find((c) => c.id === id)?.state;

/** One word for where a subject is in processing. */
export function processState(r: Row): Segment["key"] {
  if (r.stages.some((c) => c.state === "failed" || c.state === "stopped")) return "failed";
  if (r.stages.some((c) => c.state === "review")) return "waiting";
  if (r.stages.some((c) => c.state === "running")) return "running";
  if (r.complete) return "done";
  return "rest";
}

export function processSegments(subjects: Row[]): Segment[] {
  const keys: Segment["key"][] = ["done", "running", "waiting", "failed", "rest"];
  return keys.map((key) => ({ key, n: subjects.filter((r) => processState(r) === key).length }));
}

/** A subject can be judged once its functional preprocessing is done. */
export const reviewable = (r: Row) => stage(r, "preprocessing") === "done";

export function qualityCounts(subjects: Row[]) {
  const pool = subjects.filter(reviewable);
  const decided = pool.filter((r) => !!r.qc_decision).length;
  return { total: pool.length, decided, undecided: pool.length - decided };
}

export type Move = {
  id: string;
  title: string;
  text: string;
  tone: "red" | "amber";
  action: string; // button text
  to: string; // page after the workspace: "subject/sub-001", "process/ica"
};

/** What waits for the researcher, most urgent first: failures, labels to give, quality decisions. */
export function yourMove(o: Pick<Overview, "subjects" | "review">): Move[] {
  const out: Move[] = [];
  for (const r of o.subjects) {
    const bad = r.stages.filter((c) => c.state === "failed" || c.state === "stopped");
    if (!bad.length) continue;
    const stopped = bad.every((c) => c.state === "stopped");
    out.push({
      id: `failed:${r.label}`,
      title: `${bad.map((c) => c.label).join(", ")} ${stopped ? "stopped early" : "failed"} for ${r.label}`,
      text: stopped ? "The work was interrupted. Open the subject to resume it." : "Open the subject to read what happened and retry.",
      tone: "red",
      action: "See what happened",
      to: `subject/${r.label}`,
    });
  }
  for (const [i, rv] of o.review.entries()) {
    out.push({
      id: `review:${i}:${rv.subject}`,
      title: `${rv.what} (${rv.subject})`,
      text: "The pipeline is paused and uses no computer time until you save your labels.",
      tone: "amber",
      action: "Open the review",
      to: rv.page,
    });
  }
  const undecided = o.subjects.filter((r) => reviewable(r) && !r.qc_decision);
  if (undecided.length) {
    out.push({
      id: "quality",
      title: `${undecided.length} ${undecided.length === 1 ? "subject needs" : "subjects need"} a quality decision`,
      text: "Accept, review or exclude each one, with a reason. Nothing is excluded automatically.",
      tone: "amber",
      action: "Start with " + undecided[0].label,
      to: `subject/${undecided[0].label}`,
    });
  }
  return out;
}
