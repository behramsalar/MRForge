import { Badge, Button, Callout, Card, Flex, Heading, Table, Text, TextField } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { ImportSummary } from "../api/types";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

/** One row of the review table: label and session are editable until the scan is imported. */
function GroupRow({ ws, i, onOpen }: { ws: string; i: ImportSummary; onOpen: () => void }) {
  const client = useQueryClient();
  const [subject, setSubject] = useState(i.subject);
  const [session, setSession] = useState(i.session ?? "");
  const locked = i.organized > 0;
  const changed = subject.trim() !== i.subject || (session.trim() || null) !== (i.session ?? null);
  const save = useMutation({
    mutationFn: () =>
      call(
        api.PATCH("/api/workspaces/{ws_id}/imports/{import_id}/labels", {
          params: { path: { ws_id: ws, import_id: i.id } },
          body: { subject: subject.trim(), session: session.trim() || null },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["ws", ws] }),
  });
  const status = locked
    ? { text: "Imported", color: "green" as const }
    : i.needs_input > 0
      ? { text: `Needs your decision: ${i.needs_input}`, color: "amber" as const }
      : { text: "Ready", color: "gray" as const };
  return (
    <Table.Row>
      <Table.Cell>
        <Flex direction="column" gap="1">
          <Flex gap="2" align="center">
            <TextField.Root size="1" value={subject} disabled={locked} aria-label={`Subject of ${i.id}`} onChange={(e) => setSubject(e.target.value)} style={{ width: 110 }} />
            <TextField.Root size="1" value={session} disabled={locked} placeholder="ses-01" aria-label={`Session of ${i.id}`} onChange={(e) => setSession(e.target.value)} style={{ width: 90 }} />
            {changed && !locked && (
              <Button size="1" disabled={save.isPending} onClick={() => save.mutate()}>
                Save
              </Button>
            )}
          </Flex>
          {save.error && <ErrorCallout error={(save.error as ApiError).body} />}
        </Flex>
      </Table.Cell>
      <Table.Cell>
        {i.n_series} found, {i.to_import} to import
      </Table.Cell>
      <Table.Cell>
        <Badge color={status.color} variant="soft">
          {status.text}
        </Badge>
      </Table.Cell>
      <Table.Cell>
        <Button size="1" variant="soft" color="gray" onClick={onOpen}>
          Review
        </Button>
      </Table.Cell>
    </Table.Row>
  );
}

/** Scans that came from one folder or archive: a review table, "Import all that are ready" and a
 * way to give one task name to every BOLD run that still needs one. */
export function ImportGroupCard({ ws, group, busy }: { ws: string; group: ImportSummary[]; busy: boolean }) {
  const client = useQueryClient();
  const [task, setTask] = useState("");
  const open = group.filter((i) => i.organized === 0);
  const ready = open.filter((i) => i.needs_input === 0 && i.to_import > 0);
  const waiting = open.filter((i) => i.needs_input > 0);
  const refresh = () => client.invalidateQueries({ queryKey: ["ws", ws] });
  const runAll = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/imports/run-ready", {
          params: { path: { ws_id: ws } },
          body: { import_ids: open.map((i) => i.id), remove_dicom: false },
        }),
      ),
    onSuccess: refresh,
  });
  const setTaskAll = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/imports/set-task", {
          params: { path: { ws_id: ws } },
          body: { import_ids: waiting.map((i) => i.id), task: task.trim() },
        }),
      ),
    onSuccess: () => {
      setTask("");
      refresh();
    },
  });
  return (
    <Card size="2">
      <Flex direction="column" gap={space.group}>
        <Heading as="h3" size={type.sectionTitle}>
          {group.length} scans were found in {group[0].group_source ?? group[0].source_name}
        </Heading>
        <Text size={type.help} color="gray">
          Each scan becomes its own subject (labels follow the folder order; change them here if you like). Scans that
          need no decision can be imported together.
        </Text>
        <Table.Root>
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeaderCell>Subject / session</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Series</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Status</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell />
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {group.map((i) => (
              <GroupRow key={i.id} ws={ws} i={i} onOpen={() => (location.hash = href(ws, "import", i.id))} />
            ))}
          </Table.Body>
        </Table.Root>
        {waiting.length > 0 && (
          <Flex gap={space.group} align="end" wrap="wrap">
            <Flex direction="column" gap="1">
              <Text size={type.help} weight="medium">
                Task name for every BOLD run that is waiting for one
              </Text>
              <TextField.Root size="2" placeholder="e.g. rest" value={task} onChange={(e) => setTask(e.target.value)} style={{ width: 200 }} />
            </Flex>
            <Button variant="soft" disabled={!task.trim() || setTaskAll.isPending} onClick={() => setTaskAll.mutate()}>
              Use for all
            </Button>
          </Flex>
        )}
        {setTaskAll.error && <ErrorCallout error={(setTaskAll.error as ApiError).body} />}
        {runAll.error && <ErrorCallout error={(runAll.error as ApiError).body} />}
        {open.length > 0 && (
          <Flex gap={space.group} align="center" wrap="wrap">
            <Button size="3" disabled={busy || ready.length === 0 || runAll.isPending} onClick={() => runAll.mutate()}>
              Import all that are ready ({ready.length})
            </Button>
            {waiting.length > 0 && (
              <Callout.Root color="amber" size="1">
                <Callout.Text>
                  {waiting.length} {waiting.length === 1 ? "scan needs" : "scans need"} your decision first (press Review).
                </Callout.Text>
              </Callout.Root>
            )}
          </Flex>
        )}
      </Flex>
    </Card>
  );
}
