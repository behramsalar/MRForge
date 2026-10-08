import { CopyIcon } from "@radix-ui/react-icons";
import { Button, Callout, Code, Dialog, Flex, Table, Text } from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { when } from "../lib/labels";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";
import { StatusBadge } from "./ui/Badges";

/** Copy to the clipboard; falls back to doing nothing visible if the browser refuses. */
async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState<boolean | null>(null);
  return (
    <Button
      size="1"
      variant="soft"
      color="gray"
      onClick={async () => {
        setDone(await copy(text));
        setTimeout(() => setDone(null), 2000);
      }}
    >
      <CopyIcon /> {done === true ? "Copied" : done === false ? "Could not copy" : label}
    </Button>
  );
}

/** Everything recorded about one step run, with each command ready to copy, and a way to run
 * the step again with the same inputs and settings. */
export function JobRecordDialog({ ws, jobId, step }: { ws: string; jobId: number; step: string }) {
  const [open, setOpen] = useState(false);
  const client = useQueryClient();
  const record = useQuery({
    queryKey: ["ws", ws, "job-record", jobId],
    enabled: open,
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/jobs/{job_id}/record", { params: { path: { ws_id: ws, job_id: jobId } } })),
  });
  const rerun = useMutation({
    mutationFn: (force: boolean) =>
      call(api.POST("/api/workspaces/{ws_id}/jobs/{job_id}/rerun", { params: { path: { ws_id: ws, job_id: jobId } }, body: { force } })),
    onSuccess: () => client.invalidateQueries({ queryKey: ["ws", ws] }),
  });
  const r = record.data;
  const allCommands = r?.commands.map((c) => c.command).join("\n") ?? "";
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger>
        <Button size="1" variant="soft" color="gray">
          Details
        </Button>
      </Dialog.Trigger>
      <Dialog.Content maxWidth="760px">
        <Dialog.Title>{step}</Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          What MRForge recorded for this run. Nothing here is estimated.
        </Dialog.Description>
        {record.error && <ErrorCallout error={(record.error as ApiError).body} />}
        {r && (
          <Flex direction="column" gap={space.group} mt="3">
            <Flex gap={space.group} align="center" wrap="wrap">
              <StatusBadge status={r.status} />
              <Text size={type.help}>
                {r.subject ?? "no subject"}
                {r.session ? ` · ${r.session}` : ""} · started {when(r.started)}
                {r.started_by ? ` by ${r.started_by}` : ""} · step version {r.step_version}
              </Text>
            </Flex>
            {r.error_message && (
              <Callout.Root color="red" size="1">
                <Callout.Text>{r.error_message}</Callout.Text>
              </Callout.Root>
            )}
            {!r.has_provenance && (
              <Text size={type.help} color="gray">
                This run stopped before its full record was written, so only the settings are shown.
              </Text>
            )}
            <Flex direction="column" gap="1">
              <Text size={type.help} weight="medium">
                Settings
              </Text>
              <pre style={{ whiteSpace: "pre-wrap", fontSize: "var(--font-size-1)", margin: 0 }}>{JSON.stringify(r.parameters, null, 2)}</pre>
            </Flex>
            <Flex direction="column" gap="2">
              <Flex justify="between" align="center">
                <Text size={type.help} weight="medium">
                  Commands
                </Text>
                {r.commands.length > 1 && <CopyButton text={allCommands} label="Copy all commands" />}
              </Flex>
              {r.commands.length === 0 ? (
                <Text size={type.caption} color="gray">
                  No external command was recorded.
                </Text>
              ) : (
                r.commands.map((c, n) => (
                  <Flex key={n} direction="column" gap="1">
                    <Code style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{c.command}</Code>
                    <Flex gap={space.group} align="center">
                      <Text size={type.caption} color="gray">
                        exit code {c.return_code}
                      </Text>
                      <CopyButton text={c.command} label="Copy command" />
                    </Flex>
                  </Flex>
                ))
              )}
              {r.commands.length > 0 && (
                <Text size={type.caption} color="gray">
                  Run a copied command in a terminal where FSL is set up. It uses the full file paths, and overwrites the same result files.
                </Text>
              )}
            </Flex>
            {Object.keys(r.tool_versions).length > 0 && (
              <Text size={type.help}>Tools: {Object.entries(r.tool_versions).map(([k, v]) => `${k} ${v}`).join(" · ")}</Text>
            )}
            <details>
              <summary>
                <Text size={type.help}>
                  Files: {r.inputs.length} in, {r.outputs.length} out (with hashes)
                </Text>
              </summary>
              <Table.Root size="1">
                <Table.Body>
                  {[...r.inputs.map((f) => ["in", f] as const), ...r.outputs.map((f) => ["out", f] as const)].map(([kind, f]) => (
                    <Table.Row key={`${kind}${f.path}`}>
                      <Table.Cell>{kind}</Table.Cell>
                      <Table.Cell style={{ wordBreak: "break-all" }}>{f.path}</Table.Cell>
                      <Table.Cell>
                        <Code size="1">{f.sha256.slice(0, 12)}</Code>
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table.Root>
            </details>
            {rerun.error && <ErrorCallout error={(rerun.error as ApiError).body} />}
            {rerun.data && (
              <Callout.Root color="green" size="1">
                <Callout.Text>Started. Follow it in the list on this page.</Callout.Text>
              </Callout.Root>
            )}
            <Flex gap={space.group} justify="end" wrap="wrap">
              <Button variant="soft" disabled={rerun.isPending} onClick={() => rerun.mutate(false)} title="Runs it only if the earlier result is no longer valid">
                Run again
              </Button>
              <Button variant="soft" color="gray" disabled={rerun.isPending} onClick={() => rerun.mutate(true)} title="Runs it even if the earlier result is still valid">
                Run again anyway
              </Button>
              <Dialog.Close>
                <Button>Close</Button>
              </Dialog.Close>
            </Flex>
          </Flex>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
