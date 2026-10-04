import { Button, Callout, Card, Flex, Select, Text } from "@radix-ui/themes";
import { useState } from "react";
import { useOverview, useSubjects } from "../api/hooks";
import type { WorkspaceState } from "../api/types";
import { ConfirmProcessDialog } from "../components/ConfirmProcessDialog";
import { JobsPanel } from "../components/JobsPanel";
import { QcPanel } from "../components/QcPanel";
import { StageBadge } from "../components/ui/Badges";
import { PageHeader } from "../components/ui/Layout";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

/** The default way to start work: pick a subject, review the plan, confirm. */
export function FullProcessingPage({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  const subjects = useSubjects(ws);
  const overview = useOverview(ws);
  const [chosen, setChosen] = useState<string | undefined>();
  const [confirm, setConfirm] = useState(false);
  const labels = (subjects.data ?? []).filter((s) => s.files.length > 0).map((s) => s.label);
  const subject = chosen && labels.includes(chosen) ? chosen : labels[0];
  const row = overview.data?.subjects.find((s) => s.label === subject);
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");
  const jobs = (state?.jobs ?? []).filter((j) => j.subject === subject);
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader
        title="Full processing"
        description="Runs every processing stage for a subject, one after another: the recommended way to prepare data for analysis."
      />
      {subjects.data && labels.length === 0 && (
        <Callout.Root>
          <Callout.Text>
            There is no data to process yet. <a href={href(ws, "data")}>Import scans first.</a>
          </Callout.Text>
        </Callout.Root>
      )}
      {subject && (
        <Card size="3">
          <Flex direction="column" gap={space.group}>
            <Flex gap={space.group} align="end" wrap="wrap">
              <Flex direction="column" gap="1">
                <Text size={type.help} weight="medium">
                  Subject
                </Text>
                <Select.Root value={subject} onValueChange={setChosen}>
                  <Select.Trigger />
                  <Select.Content>
                    {labels.map((l) => (
                      <Select.Item key={l} value={l}>
                        {l}
                      </Select.Item>
                    ))}
                  </Select.Content>
                </Select.Root>
              </Flex>
              <Button size="3" disabled={busy} onClick={() => setConfirm(true)}>
                Process {subject}
              </Button>
            </Flex>
            {row && (
              <Flex gap={space.group} wrap="wrap" align="center">
                <Text size={type.help} color="gray">
                  Now:
                </Text>
                <Flex gap={space.inline} align="center">
                  <Text size={type.help}>Anatomical</Text>
                  <StageBadge state={row.anatomical.state} detail={row.anatomical.detail} />
                </Flex>
                <Flex gap={space.inline} align="center">
                  <Text size={type.help}>Functional</Text>
                  <StageBadge state={row.functional.state} detail={row.functional.detail} />
                </Flex>
              </Flex>
            )}
            <Text size={type.help} color="gray">
              You will see exactly what runs, with the settings, before anything starts. To run one kind of
              processing on its own, use the other entries under Process.
            </Text>
          </Flex>
        </Card>
      )}
      {subject && <ConfirmProcessDialog ws={ws} subject={subject} open={confirm} onOpenChange={setConfirm} />}
      <JobsPanel ws={ws} jobs={jobs} busy={busy} />
      {subject && <QcPanel ws={ws} subject={subject} />}
    </Flex>
  );
}
