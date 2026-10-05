import { CheckIcon, ClockIcon, Cross2Icon, ExclamationTriangleIcon, PersonIcon } from "@radix-ui/react-icons";
import { Badge, Button, Dialog, Flex, Progress, Spinner, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useTick } from "../api/hooks";
import type { ProgressStep } from "../api/types";
import { elapsed } from "../lib/labels";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";
import { stepName } from "./JobsPanel";
import { LogButton } from "./LogButton";

function icon(state: ProgressStep["state"]): ReactNode {
  switch (state) {
    case "done":
      return <CheckIcon color="var(--green-9)" />;
    case "reused":
      return <CheckIcon color="var(--gray-9)" />;
    case "running":
      return <Spinner />;
    case "review":
      return <PersonIcon color="var(--amber-9)" />;
    case "failed":
      return <Cross2Icon color="var(--red-9)" />;
    case "stopped":
      return <ExclamationTriangleIcon color="var(--orange-9)" />;
    default:
      return <ClockIcon color="var(--gray-8)" />;
  }
}

const label: Record<ProgressStep["state"], string> = {
  waiting: "Waiting",
  running: "Running",
  review: "Waiting for you",
  done: "Done",
  reused: "Already done, not repeated",
  failed: "Failed",
  stopped: "Stopped early",
};

/**
 * Live view of a running operation: how far it is, which step runs now and what the tool is
 * doing at this moment (refreshed every two seconds while it runs).
 */
export function LiveProgressDialog({ ws, operationId, trigger }: { ws: string; operationId: number; trigger: ReactNode }) {
  const [open, setOpen] = useState(false);
  const progress = useQuery({
    queryKey: ["ws", ws, "progress", operationId],
    enabled: open,
    refetchInterval: (q) => (q.state.data && !["Queued", "Running"].includes(q.state.data.status) ? false : 2000),
    queryFn: () =>
      call(
        api.GET("/api/workspaces/{ws_id}/operations/{op_id}/progress", {
          params: { path: { ws_id: ws, op_id: operationId } },
        }),
      ),
  });
  const p = progress.data;
  useTick(open && !!p && ["Queued", "Running"].includes(p.status));
  const running = p?.steps.find((s) => s.state === "running");
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger>{trigger}</Dialog.Trigger>
      <Dialog.Content maxWidth="640px">
        <Dialog.Title>{p?.title ?? "Progress"}</Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          {p
            ? `${p.status === "Running" || p.status === "Queued" ? "Running for " : "Took "}${elapsed(p.started, p.finished)}${p.started_by ? ` · started by ${p.started_by}` : ""}`
            : "Loading…"}
        </Dialog.Description>
        <Flex direction="column" gap={space.group} mt="4">
          {progress.error && <ErrorCallout error={(progress.error as ApiError).body} />}
          {p && p.total > 0 && (
            <Flex direction="column" gap="1">
              <Progress value={Math.round((100 * p.done) / p.total)} color="orange" aria-label="Progress" />
              <Text size={type.help} color="gray">
                {p.done} of {p.total} steps finished
                {p.current !== null && p.current !== undefined && running ? ` · now step ${p.current + 1}` : ""}
              </Text>
            </Flex>
          )}
          {p?.steps.map((s) => (
            <Flex key={s.id} direction="column" gap="1">
              <Flex align="center" gap={space.inline}>
                <Flex style={{ width: 20 }} justify="center">
                  {icon(s.state)}
                </Flex>
                <Text size={type.body} weight={s.state === "running" ? "bold" : "regular"} color={s.state === "waiting" ? "gray" : undefined}>
                  {stepName[s.step] ?? s.step}
                </Text>
                {s.run && (
                  <Badge variant="soft" color="gray">
                    {s.run}
                  </Badge>
                )}
                <Text size={type.caption} color="gray" style={{ marginLeft: "auto" }}>
                  {label[s.state]}
                  {s.started && (s.state === "running" || s.state === "done") ? ` · ${elapsed(s.started, s.finished)}` : ""}
                </Text>
              </Flex>
              {s.state === "review" && (
                <Flex style={{ paddingLeft: 28 }}>
                  <Text size={type.help} color="amber">
                    Waiting for you: <a href={href(ws, "process", "ica")}>open the review</a> to label the components.
                  </Text>
                </Flex>
              )}
              {s.state === "running" && (
                <Flex direction="column" gap="1" style={{ paddingLeft: 28 }}>
                  {s.now && (
                    <Text size={type.help} color="orange">
                      Now: {s.now}
                    </Text>
                  )}
                  {s.live.length > 0 && (
                    <details>
                      <summary>
                        <Text size={type.caption} color="gray">
                          Technical details
                        </Text>
                      </summary>
                      <pre style={{ whiteSpace: "pre-wrap", fontSize: "var(--font-size-1)", margin: 0, maxHeight: 160, overflow: "auto" }}>
                        {s.live.join("\n")}
                      </pre>
                    </details>
                  )}
                </Flex>
              )}
            </Flex>
          ))}
          {p && p.total === 0 && (
            <pre style={{ whiteSpace: "pre-wrap", fontSize: "var(--font-size-1)", margin: 0 }}>
              {p.log_tail.length ? p.log_tail.join("\n") : "Working…"}
            </pre>
          )}
        </Flex>
        <Flex justify="between" mt="4">
          <LogButton ws={ws} target={{ kind: "operation", id: operationId }} label="Open the full log" />
          <Dialog.Close>
            <Button variant="soft">Close</Button>
          </Dialog.Close>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
