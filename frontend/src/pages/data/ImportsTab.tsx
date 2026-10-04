import { Badge, Button, Callout, Card, Checkbox, Flex, Grid, Heading, Text } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { ApiError, call } from "../../api/call";
import { useImport } from "../../api/hooks";
import type { ImportSummary, OperationInfo, WorkspaceState } from "../../api/types";
import { ErrorCallout } from "../../components/ErrorCallout";
import { SeriesDetail } from "../../components/SeriesDetail";
import { SeriesTable } from "../../components/SeriesTable";
import { UndoImportDialog } from "../../components/UndoImportDialog";
import { EmptyState } from "../../components/ui/Layout";
import { when } from "../../lib/labels";
import { href } from "../../lib/router";
import { space, type } from "../../theme/tokens";
import { NewImportDialog } from "./NewImportDialog";

function lastOperation(state: WorkspaceState | null, kind: string, importId: string): OperationInfo | undefined {
  return [...(state?.operations ?? [])]
    .reverse()
    .find((o) => o.kind === kind && (o.result?.import_id === importId || o.title.includes(importId)));
}

function importState(i: ImportSummary): { label: string; color: "green" | "amber" | "gray" } {
  if (i.needs_input > 0) return { label: "Needs your input", color: "amber" };
  if (i.organized > 0) return { label: "Imported", color: "green" };
  return { label: "Ready to import", color: "gray" };
}

/** Imports of this workspace: the list, the series of the chosen import and the details of the
 * chosen series, with everything needed to decide and import. */
export function ImportsTab({ ws, importId, state }: { ws: string; importId?: string; state: WorkspaceState | null }) {
  const client = useQueryClient();
  const imports = state?.imports ?? [];
  const selected = importId ?? imports[imports.length - 1]?.id;
  const detail = useImport(ws, selected);
  const d = detail.data;
  const [removeDicom, setRemoveDicom] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [scanOp, setScanOp] = useState<number | null>(null);
  const [uid, setUid] = useState<string | undefined>();
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");

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

  // When the scan this page started finishes, show its series.
  useEffect(() => {
    if (scanOp === null) return;
    const op = state?.operations.find((o) => o.id === scanOp);
    if (op?.status === "Completed" && typeof op.result?.import_id === "string") {
      setScanOp(null);
      location.hash = href(ws, "data", op.result.import_id);
    } else if (op && op.status !== "Queued" && op.status !== "Running") setScanOp(null);
  }, [state, scanOp, ws]);

  const row = d?.series.find((s) => s.uid === uid) ?? d?.series.find((s) => s.action === "ask") ?? d?.series[0];
  const runOp = selected ? lastOperation(state, "import_run", selected) : undefined;
  const bids = typeof runOp?.result?.bids_report === "string" ? runOp.result.bids_report : null;
  const justImported = runOp?.status === "Completed" && d && d.organized > 0;

  if (state && imports.length === 0) {
    return (
      <EmptyState
        title="Start your first import"
        text="Choose the folder or ZIP with your scanner files. MRForge reads them, shows what it found and asks only about what it cannot decide itself."
      >
        <NewImportDialog ws={ws} disabled={busy} onStarted={setScanOp} />
      </EmptyState>
    );
  }

  return (
    <Flex direction="column" gap={space.section}>
      <Flex gap={space.group} align="stretch" wrap="wrap">
        <NewImportDialog ws={ws} disabled={busy} onStarted={setScanOp} />
        {imports.map((i) => {
          const st = importState(i);
          return (
            <Card key={i.id} asChild size="2" style={{ minWidth: 210 }}>
              <a
                href={href(ws, "data", i.id)}
                style={{ textDecoration: "none", outline: i.id === selected ? "2px solid var(--accent-9)" : undefined }}
              >
                <Flex direction="column" gap="1">
                  <Text weight="bold" size={type.body}>
                    {i.subject}
                    {i.session ? ` · ${i.session}` : ""}
                  </Text>
                  <Text size={type.caption} color="gray" style={{ wordBreak: "break-all" }}>
                    {i.source_name}
                  </Text>
                  <Flex gap={space.inline} wrap="wrap" mt="1">
                    <Badge color={st.color} variant="soft">
                      {st.label}
                    </Badge>
                  </Flex>
                  <Text size={type.caption} color="gray">
                    {when(i.created)}
                    {i.created_by ? ` · ${i.created_by}` : ""}
                  </Text>
                </Flex>
              </a>
            </Card>
          );
        })}
      </Flex>
      <Grid columns={{ initial: "1", lg: "minmax(0, 1fr) 340px" }} gap={space.group} align="start">
      <Flex direction="column" gap={space.group} style={{ minWidth: 0 }}>
        {detail.error && <ErrorCallout error={(detail.error as ApiError).body} />}
        {d && (
          <>
            <Flex align="center" gap={space.group} wrap="wrap">
              <Heading size={type.sectionTitle}>
                {d.subject}
                {d.session ? ` · ${d.session}` : ""}
              </Heading>
              <Badge variant="soft" color="gray">
                {d.n_series} series found
              </Badge>
              {d.created_by && (
                <Badge variant="soft" color="gray">
                  Imported by {d.created_by}
                </Badge>
              )}
            </Flex>
            {d.needs_input > 0 && (
              <Callout.Root color="amber">
                <Callout.Text>
                  {d.needs_input} {d.needs_input === 1 ? "series needs" : "series need"} your input. They are not
                  imported until you decide (press Decide on the highlighted rows).
                </Callout.Text>
              </Callout.Root>
            )}
            {d.warnings.length > 0 && (
              <Callout.Root color="gray">
                <Callout.Text>{d.warnings.join(" ")}</Callout.Text>
              </Callout.Root>
            )}
            {d.organized > 0 && (
              <Callout.Root color="gray">
                <Flex align="center" justify="between" gap={space.group} wrap="wrap" style={{ width: "100%" }}>
                  <Callout.Text>
                    This import is in the data folder, so its series are locked. To change a decision (skip a
                    series, rename a task), undo the import, change it, and import again.
                  </Callout.Text>
                  <UndoImportDialog ws={ws} importId={d.id} subject={d.subject} />
                </Flex>
              </Callout.Root>
            )}
            {d.organized === 0 && d.undone && (
              <Callout.Root color="green">
                <Callout.Text>
                  This import was undone. Change your decisions in the table, then import again.
                </Callout.Text>
              </Callout.Root>
            )}
            <SeriesTable ws={ws} detail={d} selected={row?.uid} onSelect={setUid} />

            <Flex direction="column" gap={space.group}>
              <Button variant="ghost" size="1" style={{ alignSelf: "flex-start" }} onClick={() => setShowMore(!showMore)}>
                {showMore ? "Hide advanced options" : "Advanced options"}
              </Button>
              {showMore && (
                <Text as="label" size={type.help}>
                  <Flex gap={space.inline} align="start">
                    <Checkbox checked={removeDicom} onCheckedChange={(v) => setRemoveDicom(v === true)} />
                    Remove MRForge's copy of the scanner files afterwards (only if you keep the originals elsewhere; it
                    saves disk space)
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
                  <Text weight="bold">Imported into {d.subject}. Your data is ready for processing.</Text>
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
                      <a href={href(ws, "process")}>Next: process the data</a>
                    </Button>
                  </Flex>
                </Flex>
              </Callout.Root>
            )}
          </>
        )}
      </Flex>

      {d && row && <SeriesDetail ws={ws} detail={d} row={row} />}
      </Grid>
    </Flex>
  );
}
