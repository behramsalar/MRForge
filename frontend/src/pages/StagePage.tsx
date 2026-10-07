import { Button, Card, Flex, Select, Text } from "@radix-ui/themes";
import { useState } from "react";
import { useSubjects } from "../api/hooks";
import type { WorkspaceState } from "../api/types";
import { ConfirmProcessDialog } from "../components/ConfirmProcessDialog";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

/** One processing stage on its own, for a subject whose earlier stages are done. The stage list
 * and the settings come from the plan, so this page only chooses the subject and the stage. */
export function StagePage({
  ws,
  state,
  stage,
  title,
  description,
}: {
  ws: string;
  state: WorkspaceState | null;
  stage: string;
  title: string;
  description: string;
}) {
  const subjects = useSubjects(ws);
  const [chosen, setChosen] = useState<string | undefined>();
  const [confirm, setConfirm] = useState(false);
  const labels = (subjects.data ?? []).filter((s) => s.files.length > 0).map((s) => s.label);
  const subject = chosen && labels.includes(chosen) ? chosen : labels[0];
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader title={title} description={description} />
      {subjects.data && labels.length === 0 && (
        <EmptyState
          title="There is no data to process yet"
          text="Import your scans first."
          action="Import scans"
          href={href(ws, "data")}
        />
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
                Run {title.toLowerCase()} for {subject}
              </Button>
            </Flex>
            <Text size={type.help} color="gray">
              The earlier stages must be done already; their results are used as they are. You will see exactly what
              runs before anything starts.
            </Text>
          </Flex>
        </Card>
      )}
      {subject && <ConfirmProcessDialog ws={ws} subject={subject} open={confirm} onOpenChange={setConfirm} onlyStage={stage} />}
    </Flex>
  );
}
