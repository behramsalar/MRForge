import { Badge, Button, Callout, Card, Checkbox, Code, Flex, Heading, Select, Text, TextField } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useImport } from "../api/hooks";
import type { OperationInfo, WorkspaceState } from "../api/types";
import { ErrorCallout } from "../components/ErrorCallout";
import { FolderPicker } from "../components/FolderPicker";
import { SeriesTable } from "../components/SeriesTable";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

function lastOperation(state: WorkspaceState | null, kind: string, importId: string): OperationInfo | undefined {
  return [...(state?.operations ?? [])]
    .reverse()
    .find((o) => o.kind === kind && (o.result?.import_id === importId || o.title.includes(importId)));
}

export function ImportPage({ ws, importId, state }: { ws: string; importId?: string; state: WorkspaceState | null }) {
  const client = useQueryClient();
  const imports = state?.imports ?? [];
  const selected = importId ?? imports[imports.length - 1]?.id;
  const detail = useImport(ws, selected);
  const [picker, setPicker] = useState(false);
  const [source, setSource] = useState<{ path: string; name: string } | null>(null);
  const [subject, setSubject] = useState("");
  const [removeDicom, setRemoveDicom] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [scanOp, setScanOp] = useState<number | null>(null);
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");

  const scan = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/imports/scan", {
          params: { path: { ws_id: ws } },
          body: { source: source!.path, subject: subject.trim() || null },
        }),
      ),
    onSuccess: (r) => setScanOp(r.operation_id),
  });
  const run = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/imports/{import_id}/run", {
          params: { path: { ws_id: ws, import_id: selected! } },
          body: { remove_dicom: removeDicom },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["ws", ws] }),
  });

  // When the scan this page started finishes, show its series table.
  useEffect(() => {
    if (scanOp === null) return;
    const op = state?.operations.find((o) => o.id === scanOp);
    if (op?.status === "Completed" && typeof op.result?.import_id === "string") {
      setScanOp(null);
      setSource(null);
      location.hash = href(ws, "data", op.result.import_id);
    } else if (op && op.status !== "Queued" && op.status !== "Running") setScanOp(null);
  }, [state, scanOp, ws]);

  const d = detail.data;
  const runOp = selected ? lastOperation(state, "import_run", selected) : undefined;
  const bids = typeof runOp?.result?.bids_report === "string" ? runOp.result.bids_report : null;
  const justImported = runOp?.status === "Completed" && d && d.organized > 0;

  return (
    <Flex direction="column" gap={space.section}>
      <Flex direction="column" gap="1">
        <Heading size={type.pageTitle}>Import scans</Heading>
        <Text color="gray" size={type.body}>
          Choose the scanner files. MRForge reads them, tells you what it found, and asks you only
          about what it cannot decide itself.
        </Text>
      </Flex>

      <Card>
        <Flex direction="column" gap={space.group}>
          <Heading size={type.sectionTitle}>Add scanner files</Heading>
          <Flex gap={space.group} align="center" wrap="wrap">
            <Button variant="soft" onClick={() => setPicker(true)}>
              {source ? "Choose another folder" : "Choose folder or ZIP"}
            </Button>
            {source && (
              <Text size={type.body}>
                <Code>{source.name}</Code>
              </Text>
            )}
          </Flex>
          {source && (
            <Flex gap={space.group} align="end" wrap="wrap">
              <Flex direction="column" gap="1">
                <Text size={type.help} weight="medium">
                  Subject label (optional)
                </Text>
                <TextField.Root placeholder="next free, e.g. sub-002" value={subject} onChange={(e) => setSubject(e.target.value)} />
              </Flex>
              <Button disabled={busy || scan.isPending} onClick={() => scan.mutate()}>
                Read scanner files
              </Button>
            </Flex>
          )}
          {scan.error && <ErrorCallout error={(scan.error as ApiError).body} />}
          <Text size={type.caption} color="gray">
            Your original files are copied into the workspace and never changed.
          </Text>
        </Flex>
      </Card>
      <FolderPicker open={picker} onOpenChange={setPicker} onPick={(path, name) => setSource({ path, name })} />

      {imports.length > 1 && (
        <Flex align="center" gap={space.group}>
          <Text size={type.help}>Showing</Text>
          <Select.Root value={selected} onValueChange={(v) => (location.hash = href(ws, "data", v))}>
            <Select.Trigger />
            <Select.Content>
              {imports.map((i) => (
                <Select.Item key={i.id} value={i.id}>
                  {i.subject} ({i.source_name})
                </Select.Item>
              ))}
            </Select.Content>
          </Select.Root>
        </Flex>
      )}

      {detail.error && <ErrorCallout error={(detail.error as ApiError).body} />}
      {d && (
        <Flex direction="column" gap={space.group}>
          <Flex align="center" gap={space.group} wrap="wrap">
            <Heading size={type.sectionTitle}>
              {d.subject}
              {d.session ? ` · ${d.session}` : ""}
            </Heading>
            <Badge variant="soft" color="gray">
              {d.n_series} series found
            </Badge>
          </Flex>
          {d.needs_input > 0 && (
            <Callout.Root color="amber">
              <Callout.Text>
                {d.needs_input} {d.needs_input === 1 ? "series needs" : "series need"} your input. They
                are not imported until you decide (press Decide on the highlighted rows).
              </Callout.Text>
            </Callout.Root>
          )}
          {d.warnings.length > 0 && (
            <Callout.Root color="gray">
              <Callout.Text>{d.warnings.join(" ")}</Callout.Text>
            </Callout.Root>
          )}
          <SeriesTable ws={ws} detail={d} />

          <Flex direction="column" gap={space.group}>
            <Button variant="ghost" size="1" style={{ alignSelf: "flex-start" }} onClick={() => setShowMore(!showMore)}>
              {showMore ? "Hide advanced options" : "Advanced options"}
            </Button>
            {showMore && (
              <Text as="label" size={type.help}>
                <Flex gap={space.inline} align="start">
                  <Checkbox checked={removeDicom} onCheckedChange={(v) => setRemoveDicom(v === true)} />
                  Remove MRForge's copy of the scanner files afterwards (only if you keep the originals
                  elsewhere; it saves disk space)
                </Flex>
              </Text>
            )}
            <Flex gap={space.group} align="center" wrap="wrap">
              <Button size="3" disabled={busy || run.isPending || d.to_import === 0} onClick={() => run.mutate()}>
                Import {d.to_import} {d.to_import === 1 ? "series" : "series"}
              </Button>
              {d.to_import === 0 && (
                <Text size={type.help} color="gray">
                  Nothing is set to be imported yet.
                </Text>
              )}
            </Flex>
            {run.error && <ErrorCallout error={(run.error as ApiError).body} />}
          </Flex>

          {justImported && (
            <Callout.Root color="green">
              <Flex direction="column" gap={space.inline} style={{ width: "100%" }}>
                <Text weight="bold">
                  Imported into {d.subject}. Your data is ready for processing.
                </Text>
                {bids && (
                  <details>
                    <summary>
                      <Text size={type.help}>BIDS check (data format check)</Text>
                    </summary>
                    <pre style={{ whiteSpace: "pre-wrap", fontSize: "var(--font-size-1)" }}>{bids}</pre>
                  </details>
                )}
                <Flex>
                  <Button asChild>
                    <a href={href(ws, "process", "anat")}>Next: anatomical processing</a>
                  </Button>
                </Flex>
              </Flex>
            </Callout.Root>
          )}
        </Flex>
      )}
      {!d && imports.length === 0 && state && (
        <Callout.Root>
          <Callout.Text>Nothing has been imported yet. Choose your scanner files above to begin.</Callout.Text>
        </Callout.Root>
      )}
    </Flex>
  );
}
