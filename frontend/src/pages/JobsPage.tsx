import { MagnifyingGlassIcon } from "@radix-ui/react-icons";
import { Button, Card, Flex, SegmentedControl, Switch, Table, Text, TextField } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import type { JobInfo, OperationInfo, WorkspaceState } from "../api/types";
import { JobsPanel, latestJobs, stepName } from "../components/JobsPanel";
import { JobRecordDialog } from "../components/JobRecordDialog";
import { LogButton } from "../components/LogButton";
import { StatusBadge } from "../components/ui/Badges";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { elapsed, when } from "../lib/labels";
import { space, type } from "../theme/tokens";

type Filter = "all" | "running" | "failed" | "completed";

const matches: Record<Filter, (status: string) => boolean> = {
  all: () => true,
  running: (s) => s === "Queued" || s === "Running" || s === "Waiting",
  failed: (s) => s === "Failed" || s === "Interrupted" || s === "Cancelled",
  completed: (s) => s === "Completed",
};

/** One row of the history: a processing step, or a task such as reading scanner files. */
type Row = {
  key: string;
  what: string;
  run: string;
  subject: string;
  status: string;
  who: string;
  started: string | null | undefined;
  finished: string | null | undefined;
  log: { kind: "job" | "operation"; id: number };
  at: number;
};

const PAGE = 20;
const stamp = (v: string | null | undefined) => (v ? new Date(v.endsWith("Z") || v.includes("+") ? v : v + "Z").getTime() : 0);

function jobRow(j: JobInfo): Row {
  return {
    key: `j${j.id}`, what: stepName[j.step] ?? j.step, run: j.run, subject: j.subject ?? "",
    status: j.status, who: j.started_by ?? "", started: j.started, finished: j.finished,
    log: { kind: "job", id: j.id }, at: stamp(j.started ?? j.created),
  };
}

function taskRow(o: OperationInfo): Row {
  return {
    key: `o${o.id}`, what: o.title, run: "", subject: "", status: o.status, who: o.started_by ?? "",
    started: o.started ?? o.created, finished: o.finished, log: { kind: "operation", id: o.id },
    at: stamp(o.started ?? o.created),
  };
}

/** Tasks other than pipelines (a pipeline is already listed step by step). Unless earlier
 * attempts are wanted, a failed task that was later repeated with the same title is hidden. */
function tasks(ops: OperationInfo[], earlier: boolean): Row[] {
  const rest = ops.filter((o) => o.kind !== "pipeline");
  const kept = earlier
    ? rest
    : rest.filter((o) => !(o.status !== "Completed" && rest.some((x) => x.id > o.id && x.title === o.title && x.status === "Completed")));
  return kept.map(taskRow);
}

/** Everything that ran in this workspace: newest first, filterable, with each step's log. */
export function JobsPage({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [earlier, setEarlier] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const jobs = useMemo(() => state?.jobs ?? [], [state]);
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");
  const ops = state?.operations;
  const rows = useMemo(() => {
    const steps = (earlier ? jobs : latestJobs(jobs)).map(jobRow);
    return [...steps, ...tasks(ops ?? [], earlier)]
      .filter((r) => matches[filter](r.status))
      .filter((r) => `${r.what} ${r.run} ${r.subject} ${r.who}`.toLowerCase().includes(query.trim().toLowerCase()))
      .sort((a, b) => b.at - a.at);
  }, [jobs, ops, earlier, filter, query]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const at = Math.min(page, pages - 1);
  const shown = rows.slice(at * PAGE, at * PAGE + PAGE);
  const showRun = rows.some((r) => r.run);
  const showWho = rows.some((r) => r.who);
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader title="Jobs" description="Everything that ran in this workspace (steps and tasks such as reading scanner files), newest first." />
      {state && jobs.length === 0 && (state.operations.length === 0) ? (
        <EmptyState title="Nothing has run yet" text="Steps you start from the Process page show up here, with their logs." />
      ) : (
        <>
          <JobsPanel ws={ws} jobs={jobs} busy={busy} hideTable />
          <Flex gap={space.group} align="center" wrap="wrap" justify="between">
            <SegmentedControl.Root value={filter} onValueChange={(v) => setFilter(v as Filter)}>
              <SegmentedControl.Item value="all">All</SegmentedControl.Item>
              <SegmentedControl.Item value="running">Running or waiting</SegmentedControl.Item>
              <SegmentedControl.Item value="failed">Failed or stopped</SegmentedControl.Item>
              <SegmentedControl.Item value="completed">Finished</SegmentedControl.Item>
            </SegmentedControl.Root>
            <TextField.Root placeholder="Search steps, subjects, people" value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} aria-label="Search the history" style={{ minWidth: 240 }}>
              <TextField.Slot>
                <MagnifyingGlassIcon />
              </TextField.Slot>
            </TextField.Root>
            <Text as="label" size={type.help}>
              <Flex gap="2" align="center">
                <Switch checked={earlier} onCheckedChange={setEarlier} />
                Show earlier attempts too
              </Flex>
            </Text>
          </Flex>
          <Card>
            {rows.length === 0 ? (
              <Text size={type.help}>No steps match this filter.</Text>
            ) : (
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
                  {shown.map((r) => (
                    <Table.Row key={r.key}>
                      <Table.RowHeaderCell>{r.what}</Table.RowHeaderCell>
                      {showRun && <Table.Cell>{r.run}</Table.Cell>}
                      <Table.Cell>{r.subject}</Table.Cell>
                      <Table.Cell>
                        <StatusBadge status={r.status} />
                      </Table.Cell>
                      {showWho && <Table.Cell>{r.who}</Table.Cell>}
                      <Table.Cell>{when(r.started)}</Table.Cell>
                      <Table.Cell>{elapsed(r.started, r.finished)}</Table.Cell>
                      <Table.Cell>
                        <Flex gap="2" justify="end">
                          {r.log.kind === "job" && <JobRecordDialog ws={ws} jobId={r.log.id} step={r.what} />}
                          <LogButton ws={ws} target={r.log} />
                        </Flex>
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table.Root>
            )}
            {pages > 1 && (
              <Flex justify="between" align="center" mt="3">
                <Text size={type.help} color="gray">
                  {at * PAGE + 1}-{Math.min(rows.length, at * PAGE + PAGE)} of {rows.length}
                </Text>
                <Flex gap="2">
                  <Button size="1" variant="soft" color="gray" disabled={at === 0} onClick={() => setPage(at - 1)}>
                    Previous
                  </Button>
                  <Button size="1" variant="soft" color="gray" disabled={at >= pages - 1} onClick={() => setPage(at + 1)}>
                    Next
                  </Button>
                </Flex>
              </Flex>
            )}
          </Card>
        </>
      )}
    </Flex>
  );
}
