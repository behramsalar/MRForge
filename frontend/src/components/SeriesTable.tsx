import { Badge, Button, Callout, Card, Checkbox, Dialog, Flex, Select, Table, Text, TextField } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { ImportDetail, SeriesRow } from "../api/types";
import { kindName } from "../lib/labels";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";
import { ActionBadge, ConfidenceBadge } from "./ui/Badges";

export function size(s: SeriesRow): string {
  const vols = s.volumes && s.volumes > 1 ? ` × ${s.volumes}` : "";
  return `${s.matrix}${vols}`;
}

export function detected(s: SeriesRow): string {
  const extra = Object.entries(s.entities)
    .map(([k, v]) => `${k} ${v}`)
    .join(", ");
  return kindName(s.kind) + (extra ? ` (${extra})` : "");
}

/** The user's decision about one series: what it is, its task name, or leave it out. */
export function DecisionDialog({ ws, detail, row }: { ws: string; detail: ImportDetail; row: SeriesRow }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState(row.action === "skip" ? "" : row.kind);
  const [task, setTask] = useState(row.entities.task ?? "");
  const [skip, setSkip] = useState(row.action === "skip");
  const [showMore, setShowMore] = useState(false);
  const [acq, setAcq] = useState(row.entities.acq ?? "");
  const kindInfo = detail.kinds.find((k) => k.kind === kind);
  const needsTask = kindInfo?.needs.includes("task") || row.needs.includes("task");

  const save = useMutation({
    mutationFn: () =>
      call(
        api.PATCH("/api/workspaces/{ws_id}/imports/{import_id}/series-by-id/{uid}", {
          params: { path: { ws_id: ws, import_id: detail.id, uid: row.uid } },
          body: skip
            ? { skip: true }
            : {
                skip: false,
                kind: kind && kind !== row.kind ? kind : undefined,
                task: needsTask && task ? task : undefined,
                acq: acq || undefined,
              },
        }),
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["ws", ws] });
      setOpen(false);
    },
  });

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger>
        <Button size="1" variant={row.action === "ask" ? "solid" : "soft"} color={row.action === "ask" ? "amber" : undefined}>
          {row.action === "ask" ? "Decide" : "Change"}
        </Button>
      </Dialog.Trigger>
      <Dialog.Content maxWidth="520px">
        <Dialog.Title>
          Series {row.number}: {row.label}
        </Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          {size(row)} · {row.n_files} files
        </Dialog.Description>
        {row.reasons.length > 0 && (
          <Callout.Root size="1" mt="3" color="gray">
            <Callout.Text>Why MRForge thinks this: {row.reasons.join("; ")}.</Callout.Text>
          </Callout.Root>
        )}
        <Flex direction="column" gap={space.group} mt="4">
          <Text as="label" size={type.body}>
            <Flex gap={space.inline} align="center">
              <Checkbox checked={skip} onCheckedChange={(v) => setSkip(v === true)} />
              Leave this series out (do not import it)
            </Flex>
          </Text>
          {!skip && (
            <>
              <Flex direction="column" gap="1">
                <Text size={type.help} weight="medium">
                  What is it?
                </Text>
                <Select.Root value={kind} onValueChange={setKind}>
                  <Select.Trigger placeholder="Choose a type" />
                  <Select.Content>
                    {detail.kinds.map((k) => (
                      <Select.Item key={k.kind} value={k.kind}>
                        {kindName(k.kind)}
                      </Select.Item>
                    ))}
                  </Select.Content>
                </Select.Root>
              </Flex>
              {needsTask && (
                <Flex direction="column" gap="1">
                  <Text size={type.help} weight="medium">
                    Task name
                  </Text>
                  <TextField.Root placeholder="e.g. rest" value={task} onChange={(e) => setTask(e.target.value)} />
                  <Text size={type.caption} color="gray">
                    Letters and digits only, no spaces. Use "rest" for resting-state runs.
                  </Text>
                </Flex>
              )}
              <Button variant="ghost" size="1" style={{ alignSelf: "flex-start" }} onClick={() => setShowMore(!showMore)}>
                {showMore ? "Hide advanced options" : "Advanced options"}
              </Button>
              {showMore && (
                <Flex direction="column" gap="1">
                  <Text size={type.help} weight="medium">
                    Acquisition label (optional)
                  </Text>
                  <TextField.Root placeholder="e.g. highres" value={acq} onChange={(e) => setAcq(e.target.value)} />
                </Flex>
              )}
            </>
          )}
          {save.error && <ErrorCallout error={(save.error as ApiError).body} />}
        </Flex>
        <Flex justify="end" gap={space.group} mt="4">
          <Dialog.Close>
            <Button variant="soft" color="gray">
              Cancel
            </Button>
          </Dialog.Close>
          <Button disabled={save.isPending || (!skip && !kind)} onClick={() => save.mutate()}>
            Save
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}

/** The confirm-series table: what was found, what MRForge will do, and a way to change it. */
export function SeriesTable({
  ws,
  detail,
  selected,
  onSelect,
}: {
  ws: string;
  detail: ImportDetail;
  selected?: string;
  onSelect?: (uid: string) => void;
}) {
  const compact = !!onSelect; // the details panel next to the table shows the size
  return (
    <Card style={{ overflowX: "auto" }}>
      <Table.Root size="2">
        <Table.Header>
          <Table.Row>
            <Table.ColumnHeaderCell>#</Table.ColumnHeaderCell>
            <Table.ColumnHeaderCell>Name</Table.ColumnHeaderCell>
            {!compact && <Table.ColumnHeaderCell>Size</Table.ColumnHeaderCell>}
            <Table.ColumnHeaderCell>Detected as</Table.ColumnHeaderCell>
            <Table.ColumnHeaderCell>Confidence</Table.ColumnHeaderCell>
            <Table.ColumnHeaderCell>What happens</Table.ColumnHeaderCell>
            <Table.ColumnHeaderCell />
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {detail.series.map((s) => (
            <Table.Row
              key={s.uid}
              onClick={() => onSelect?.(s.uid)}
              style={{
                cursor: onSelect ? "pointer" : undefined,
                background:
                  s.uid === selected ? "var(--accent-a3)" : s.action === "ask" ? "var(--amber-3)" : undefined,
              }}
            >
              <Table.RowHeaderCell>{s.number}</Table.RowHeaderCell>
              <Table.Cell>{s.label}</Table.Cell>
              {!compact && <Table.Cell>{size(s)}</Table.Cell>}
              <Table.Cell>
                {detected(s)}
                {s.decided_by === "user" && (
                  <Badge ml="2" size="1" variant="outline">
                    your choice
                  </Badge>
                )}
              </Table.Cell>
              <Table.Cell>
                <ConfidenceBadge level={s.confidence} />
              </Table.Cell>
              <Table.Cell>
                {s.organized ? (
                  <Badge color="green" variant="solid">
                    Imported
                  </Badge>
                ) : (
                  <ActionBadge action={s.action} />
                )}
              </Table.Cell>
              <Table.Cell onClick={(e) => e.stopPropagation()}>
                <DecisionDialog ws={ws} detail={detail} row={s} key={`${s.uid}-${s.action}-${s.kind}`} />
              </Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table.Root>
    </Card>
  );
}
