import { Button, Code, Dialog, Flex, ScrollArea, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { call } from "../api/call";
import type { LogText } from "../api/types";
import { space, type } from "../theme/tokens";

type Target = { kind: "job"; id: number } | { kind: "operation"; id: number };

function useLog(ws: string, target: Target, open: boolean) {
  return useQuery({
    queryKey: ["log", ws, target.kind, target.id],
    enabled: open,
    queryFn: async (): Promise<LogText[]> => {
      if (target.kind === "job") {
        return call(
          api.GET("/api/workspaces/{ws_id}/jobs/{job_id}/log", {
            params: { path: { ws_id: ws, job_id: target.id } },
          }),
        );
      }
      return [
        await call(
          api.GET("/api/workspaces/{ws_id}/operations/{op_id}/log", {
            params: { path: { ws_id: ws, op_id: target.id } },
          }),
        ),
      ];
    },
  });
}

function Logs({ ws, target }: { ws: string; target: Target }) {
  const logs = useLog(ws, target, true);
  if (logs.isPending) return <Text size={type.help}>Loading…</Text>;
  const shown = (logs.data ?? []).filter((l) => l.text.trim());
  if (shown.length === 0) return <Text size={type.help}>Nothing was written to the log.</Text>;
  return (
    <Flex direction="column" gap={space.group}>
      {shown.map((l) => (
        <div key={l.name}>
          <Text size={type.caption} color="gray">
            {l.name.split("/").pop()}
          </Text>
          <ScrollArea style={{ maxHeight: 280 }}>
            <Code asChild variant="ghost" size="2">
              <pre style={{ whiteSpace: "pre-wrap" }}>{l.text}</pre>
            </Code>
          </ScrollArea>
        </div>
      ))}
    </Flex>
  );
}

/** "View log": the raw tool output, one click away from any error. */
export function LogButton({ ws, target, label = "View log" }: { ws: string; target: Target; label?: string }) {
  return (
    <Dialog.Root>
      <Dialog.Trigger>
        <Button variant="outline" size="2">
          {label}
        </Button>
      </Dialog.Trigger>
      <Dialog.Content maxWidth="720px">
        <Dialog.Title>Raw log</Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          This is the technical output of the tool. Useful if you need to ask for help.
        </Dialog.Description>
        <Logs ws={ws} target={target} />
        <Flex justify="end" mt="4">
          <Dialog.Close>
            <Button variant="soft">Close</Button>
          </Dialog.Close>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
