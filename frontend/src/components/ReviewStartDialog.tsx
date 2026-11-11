import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Callout, Dialog, Flex, Text } from "@radix-ui/themes";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { FullOptions, StagePlan } from "../api/types";
import { planRequests } from "../lib/processOptions";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

type Batch = { subjects: { subject: string; can_start: boolean; steps: number; reason?: string | null }[]; runnable: number } | null;

/** The last look before work starts: which stages run, which are left out and why, and (for
 * several subjects) who can run. Settings are not edited here; they live on the Process page. */
export function ReviewStartDialog({
  ws,
  open,
  onOpenChange,
  opts,
  subjects,
  preset,
  stages,
  canStart,
  steps,
  batch,
  doneEarlier,
}: {
  ws: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  opts: FullOptions;
  subjects: string[];
  preset?: string;
  stages: StagePlan[];
  canStart: boolean;
  steps: number;
  batch: Batch;
  doneEarlier: Record<string, number>; // stage id -> subjects that already have it
}) {
  const client = useQueryClient();
  const { one, batch: batchRequest } = planRequests(opts, subjects, preset);
  const many = subjects.length > 1;
  const start = useMutation({
    mutationFn: () =>
      many
        ? call(api.POST("/api/workspaces/{ws_id}/process-batch", { params: { path: { ws_id: ws } }, body: batchRequest }))
        : call(api.POST("/api/workspaces/{ws_id}/process", { params: { path: { ws_id: ws } }, body: one })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["ws", ws] });
      onOpenChange(false);
    },
  });
  const running = stages.filter((s) => s.enabled && s.can_run);
  const left = stages.filter((s) => !(s.enabled && s.can_run));
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="520px">
        <Dialog.Title>{many ? `Process ${subjects.length} subjects` : `Process ${subjects[0] ?? ""}`}</Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          These stages run one after another{many ? " for every subject, a few subjects at a time" : ""}. Finished, unchanged work is
          not repeated. You can close the page while it runs.
        </Dialog.Description>
        <Flex direction="column" gap={space.group} mt="4" style={{ maxHeight: "55vh", overflowY: "auto" }}>
          <Flex direction="column" gap="1">
            <Text size={type.help} weight="medium">
              Will run
            </Text>
            {running.length === 0 && <Text size={type.help} color="gray">Nothing.</Text>}
            {running.map((s) => (
              <Flex key={s.id} justify="between" gap={space.group}>
                <Text size={type.help}>{s.label}</Text>
                <Text size={type.caption} color="gray">
                  {doneEarlier[s.id] ? `${doneEarlier[s.id]} of ${subjects.length} done earlier (skipped if unchanged)` : ""}
                </Text>
              </Flex>
            ))}
          </Flex>
          {left.length > 0 && (
            <Flex direction="column" gap="1">
              <Text size={type.help} weight="medium">
                Left out
              </Text>
              {left.map((s) => (
                <Flex key={s.id} justify="between" gap={space.group}>
                  <Text size={type.help} color="gray">
                    {s.label}
                  </Text>
                  <Text size={type.caption} color="gray">
                    {!s.can_run ? s.reason : "switched off"}
                  </Text>
                </Flex>
              ))}
            </Flex>
          )}
          {batch && (
            <Flex direction="column" gap="1">
              <Text size={type.help} weight="medium">
                Subjects ({batch.runnable} of {batch.subjects.length} can run)
              </Text>
              {batch.subjects
                .filter((s) => !s.can_start)
                .map((s) => (
                  <Text key={s.subject} size={type.caption} color="orange">
                    {s.subject}: cannot run: {s.reason}
                  </Text>
                ))}
            </Flex>
          )}
          {!canStart && (
            <Callout.Root color="amber">
              <Callout.Text>Nothing can run with these choices. Switch on a stage that is possible.</Callout.Text>
            </Callout.Root>
          )}
          {start.error && <ErrorCallout error={(start.error as ApiError).body} />}
        </Flex>
        <Flex justify="between" align="center" gap={space.group} mt="4">
          <Text size={type.help} color="gray">
            {batch ? `${batch.runnable} of ${batch.subjects.length} subjects can run` : canStart ? `${steps} ${steps === 1 ? "step" : "steps"} will run` : ""}
          </Text>
          <Flex gap={space.group}>
            <Dialog.Close>
              <Button variant="soft" color="gray">
                Cancel
              </Button>
            </Dialog.Close>
            <Button size="3" disabled={!canStart || start.isPending} onClick={() => start.mutate()}>
              Start processing
            </Button>
          </Flex>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
