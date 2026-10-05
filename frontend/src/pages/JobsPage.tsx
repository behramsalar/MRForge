import { Card, Flex, SegmentedControl, Switch, Table, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import type { WorkspaceState } from "../api/types";
import { JobsPanel, latestJobs, stepName } from "../components/JobsPanel";
import { LogButton } from "../components/LogButton";
import { StatusBadge } from "../components/ui/Badges";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { elapsed, when } from "../lib/labels";
import { space, type } from "../theme/tokens";

type Filter = "all" | "running" | "failed" | "completed";

const matches: Record<Filter, (status: string) => boolean> = {
  all: () => true,
  running: (s) => s === "Queued" || s === "Running",
  failed: (s) => s === "Failed" || s === "Interrupted" || s === "Cancelled",
  completed: (s) => s === "Completed",
};

/** Everything that ran in this workspace: newest first, filterable, with each step's log. */
export function JobsPage({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [earlier, setEarlier] = useState(false);
  const jobs = useMemo(() => state?.jobs ?? [], [state]);
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");
  const rows = useMemo(
    () => (earlier ? [...jobs].reverse() : latestJobs(jobs)).filter((j) => matches[filter](j.status)),
    [jobs, earlier, filter],
  );
  const showRun = rows.some((j) => j.run);
  const showWho = rows.some((j) => j.started_by);
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader title="Jobs" description="Every processing step that ran in this workspace, newest first." />
      {state && jobs.length === 0 ? (
        <EmptyState title="Nothing has run yet" text="Steps you start from the Process page show up here, with their logs." />
      ) : (
        <>
          <JobsPanel ws={ws} jobs={jobs} busy={busy} hideTable />
          <Flex gap={space.group} align="center" wrap="wrap" justify="between">
            <SegmentedControl.Root value={filter} onValueChange={(v) => setFilter(v as Filter)}>
              <SegmentedControl.Item value="all">All</SegmentedControl.Item>
              <SegmentedControl.Item value="running">Running</SegmentedControl.Item>
              <SegmentedControl.Item value="failed">Failed or stopped</SegmentedControl.Item>
              <SegmentedControl.Item value="completed">Finished</SegmentedControl.Item>
            </SegmentedControl.Root>
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
                      <Table.Cell>
                        <LogButton ws={ws} target={{ kind: "job", id: j.id }} />
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table.Root>
            )}
          </Card>
        </>
      )}
    </Flex>
  );
}
