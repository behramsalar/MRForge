import { Button, Card, Flex, Heading, Table } from "@radix-ui/themes";
import { useMutation } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useTick } from "../api/hooks";
import type { JobInfo } from "../api/types";
import { elapsed, when } from "../lib/labels";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";
import { LogButton } from "./LogButton";
import { StatusBadge } from "./ui/Badges";

/** Plain-language names for the steps the engine runs. */
export const stepName: Record<string, string> = {
  fsl_anat: "Anatomical processing (fsl_anat)",
  bet: "Brain extraction (bet)",
  fieldmap_prep: "Prepare the fieldmap",
  feat_preproc: "Motion correction, distortion correction, smoothing and registration (FEAT)",
  func_qc: "Quality checks (motion and registration pictures)",
  func_to_mni: "Move the result to standard (MNI) space",
};

/** Latest run per subject, step and recording: older attempts would only clutter the list. */
export function latestJobs(jobs: JobInfo[]): JobInfo[] {
  const latest = new Map<string, JobInfo>();
  for (const j of jobs) latest.set(`${j.subject}/${j.label}/${j.run}`, j);
  return [...latest.values()].reverse();
}

/** Progress of steps, with the failure screen: what happened, why, what to do, View log,
 * and Retry step / Resume pipeline. */
export function JobsPanel({
  ws,
  jobs,
  busy,
  action,
  hideTable = false,
}: {
  ws: string;
  jobs: JobInfo[];
  busy: boolean;
  action?: (job: JobInfo) => ReactNode; // a button for a finished step, e.g. "View result"
  hideTable?: boolean; // only the failure messages (the Jobs page has its own history table)
}) {
  useTick(jobs.some((j) => j.status === "Running"));
  const resume = useMutation({
    mutationFn: () => call(api.POST("/api/workspaces/{ws_id}/resume", { params: { path: { ws_id: ws } } })),
  });
  const rows = latestJobs(jobs);
  if (rows.length === 0) return null;
  const showRun = rows.some((j) => j.run);
  const showWho = rows.some((j) => j.started_by);
  return (
    <Flex direction="column" gap={space.group}>
      {!hideTable && <Heading size={type.sectionTitle}>Progress</Heading>}
      {!hideTable && (
      <Card>
        <Table.Root>
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeaderCell>Step</Table.ColumnHeaderCell>
              {showRun && <Table.ColumnHeaderCell>Recording</Table.ColumnHeaderCell>}
              <Table.ColumnHeaderCell>Subject</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Status</Table.ColumnHeaderCell>
              {showWho && <Table.ColumnHeaderCell>Started by</Table.ColumnHeaderCell>}
              <Table.ColumnHeaderCell>Started</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Time</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell />
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {rows.map((j) => (
              <Table.Row key={j.id}>
                <Table.RowHeaderCell>{stepName[j.step] ?? j.step}</Table.RowHeaderCell>
                {showRun && <Table.Cell>{j.run}</Table.Cell>}
                <Table.Cell>{j.subject}</Table.Cell>
                <Table.Cell>
                  <StatusBadge status={j.status} />
                </Table.Cell>
                {showWho && <Table.Cell>{j.started_by ?? ""}</Table.Cell>}
                <Table.Cell>{when(j.started)}</Table.Cell>
                <Table.Cell>{elapsed(j.started, j.finished)}</Table.Cell>
                <Table.Cell>{j.status === "Completed" && action ? action(j) : null}</Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Root>
      </Card>
      )}
      {rows
        .filter((j) => j.error && (j.status === "Failed" || j.status === "Interrupted"))
        .map((j) => (
          <ErrorCallout
            key={j.id}
            color={j.status === "Interrupted" ? "orange" : "red"}
            error={j.error!}
            actions={
              <>
                <Button size="2" disabled={busy || resume.isPending} onClick={() => resume.mutate()}>
                  {j.status === "Interrupted" ? "Resume pipeline" : "Retry step"}
                </Button>
                <LogButton ws={ws} target={{ kind: "job", id: j.id }} />
              </>
            }
          />
        ))}
      {resume.error && <ErrorCallout error={(resume.error as ApiError).body} />}
    </Flex>
  );
}
