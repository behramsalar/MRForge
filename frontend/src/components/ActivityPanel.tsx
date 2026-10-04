import { Button, Callout, Flex, Spinner, Text } from "@radix-ui/themes";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useTick } from "../api/hooks";
import type { ErrorBody, WorkspaceState } from "../api/types";
import { elapsed } from "../lib/labels";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";
import { LogButton } from "./LogButton";

/** Always visible in a workspace: what is running now, and how the last action ended. */
export function ActivityPanel({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  const cancel = useMutation({
    mutationFn: (id: number) =>
      call(
        api.POST("/api/workspaces/{ws_id}/operations/{op_id}/cancel", {
          params: { path: { ws_id: ws, op_id: id } },
        }),
      ),
  });
  const resume = useMutation({
    mutationFn: () => call(api.POST("/api/workspaces/{ws_id}/resume", { params: { path: { ws_id: ws } } })),
  });
  useTick(!!state?.operations.some((o) => o.status === "Queued" || o.status === "Running"));
  if (!state) return null;
  const ops = state.operations;
  const latest = ops[ops.length - 1];
  const running = ops.find((o) => o.status === "Queued" || o.status === "Running");
  const runningJob = state.jobs.find((j) => j.status === "Running");
  const blocks: React.ReactNode[] = [];

  if (running) {
    blocks.push(
      <Callout.Root key="running" color="blue">
        <Callout.Icon>
          <Spinner />
        </Callout.Icon>
        <Flex align="center" justify="between" gap={space.group} wrap="wrap" style={{ width: "100%" }}>
          <Text size={type.body}>
            {running.title}…{running.started_by ? ` (started by ${running.started_by})` : ""}{" "}
            <Text color="gray" size={type.help}>
              ({elapsed(running.started ?? running.created, null)})
              {runningJob ? ` Step: ${runningJob.label}` : ""}
            </Text>
          </Text>
          <Flex gap={space.inline}>
            <LogButton ws={ws} target={{ kind: "operation", id: running.id }} label="Details" />
            <Button
              size="2"
              color="red"
              variant="soft"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate(running.id)}
            >
              Cancel
            </Button>
          </Flex>
        </Flex>
      </Callout.Root>,
    );
  } else if (latest && latest.error) {
    // A pipeline that failed because a step failed is explained on the Anatomical page by
    // the step itself; show only operations that carry their own explanation.
    const stepFailure = latest.kind === "pipeline" && state.jobs.some((j) => j.error);
    if (!stepFailure) {
      const err: ErrorBody = latest.error;
      blocks.push(
        <ErrorCallout
          key="error"
          error={err}
          color={latest.status === "Interrupted" ? "orange" : "red"}
          actions={
            <>
              {latest.kind === "pipeline" && (
                <Button size="2" disabled={resume.isPending} onClick={() => resume.mutate()}>
                  Resume pipeline
                </Button>
              )}
              <LogButton ws={ws} target={{ kind: "operation", id: latest.id }} />
            </>
          }
        />,
      );
    }
  }
  if (resume.error) blocks.push(<ErrorCallout key="resume" error={(resume.error as ApiError).body} />);
  if (cancel.error) blocks.push(<ErrorCallout key="cancel" error={(cancel.error as ApiError).body} />);
  if (blocks.length === 0) return null;
  return (
    <Flex direction="column" gap={space.group}>
      {blocks}
    </Flex>
  );
}
