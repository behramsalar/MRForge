import { DownloadIcon } from "@radix-ui/react-icons";
import { Badge, Button, Callout, Card, Checkbox, Flex, Heading, Table, Text, Tooltip } from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

const DECISION_COLOUR: Record<string, "green" | "amber" | "red"> = { accept: "green", review: "amber", exclude: "red" };

/** The ALPS result of every diffusion series in the workspace, and its export as CSV and Excel.
 * Every number is read from what the processing recorded; flags only warn. */
export function DiffusionResultsTable({ ws }: { ws: string }) {
  const client = useQueryClient();
  const [leaveOut, setLeaveOut] = useState(false);
  const rows = useQuery({
    queryKey: ["ws", ws, "alps-results"],
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/alps-results", { params: { path: { ws_id: ws } } })),
  });
  const saved = useQuery({
    queryKey: ["ws", ws, "alps-results", "exports"],
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/alps-results/exports", { params: { path: { ws_id: ws } } })),
  });
  const save = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/alps-results/export", {
          params: { path: { ws_id: ws }, query: { leave_out_excluded: leaveOut } },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["ws", ws, "alps-results", "exports"] }),
  });
  const data = rows.data ?? [];
  if (rows.error) return <ErrorCallout error={(rows.error as ApiError).body} />;
  const latest = (save.data ?? saved.data ?? []).slice(0, 2);
  return (
    <Card size="3">
      <Flex direction="column" gap={space.group}>
        <Flex justify="between" align="center" wrap="wrap" gap={space.group}>
          <Heading as="h2" size={type.sectionTitle}>
            Diffusion results
          </Heading>
          <Flex gap={space.group} align="center" wrap="wrap">
            <Text as="label" size={type.help}>
              <Flex gap="2" align="center">
                <Checkbox checked={leaveOut} onCheckedChange={(v) => setLeaveOut(v === true)} />
                Leave out subjects I excluded
              </Flex>
            </Text>
            <Button disabled={data.length === 0 || save.isPending} onClick={() => save.mutate()}>
              <DownloadIcon /> Export table (CSV and Excel)
            </Button>
          </Flex>
        </Flex>
        {data.length === 0 ? (
          <Text size={type.help} color="gray">
            No ALPS result yet. Run the diffusion stage for a subject and the numbers appear here.
          </Text>
        ) : (
          <Table.Root size="1" variant="surface">
            <Table.Header>
              <Table.Row>
                <Table.ColumnHeaderCell>Subject</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Regions</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>ALPS</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Left</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Right</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>FA</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>MD (10⁻³ mm²/s)</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Your decision</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Flags</Table.ColumnHeaderCell>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {data.map((r) => (
                <Table.Row key={r.record}>
                  <Table.RowHeaderCell>
                    <a href={href(ws, "subject", r.subject)}>{r.subject}</a>
                    {r.session ? ` ${r.session}` : ""}
                    {r.series ? ` (${r.series})` : ""}
                  </Table.RowHeaderCell>
                  <Table.Cell>
                    <Text size={type.help}>{r.regions}</Text>
                  </Table.Cell>
                  <Table.Cell>
                    <Text weight="bold">{r.alps.toFixed(3)}</Text>
                  </Table.Cell>
                  <Table.Cell>{r.alps_L.toFixed(3)}</Table.Cell>
                  <Table.Cell>{r.alps_R.toFixed(3)}</Table.Cell>
                  <Table.Cell>{r.fa.toFixed(3)}</Table.Cell>
                  <Table.Cell>{(r.md * 1000).toFixed(3)}</Table.Cell>
                  <Table.Cell>
                    {r.decision ? (
                      <Tooltip content={r.decision_reason ?? ""}>
                        <Badge color={DECISION_COLOUR[r.decision] ?? "gray"} variant="soft">
                          {r.decision}
                        </Badge>
                      </Tooltip>
                    ) : (
                      <Text color="gray">none yet</Text>
                    )}
                  </Table.Cell>
                  <Table.Cell>
                    {r.flags.length > 0 ? (
                      <Tooltip content={r.flags.join("; ")}>
                        <Badge color="amber" variant="soft">
                          {r.flags.length} to look at
                        </Badge>
                      </Tooltip>
                    ) : (
                      <Text color="gray">none</Text>
                    )}
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table.Root>
        )}
        <Text size={type.caption} color="gray">
          Numbers are the values recorded when each series was processed. Flags are only a prompt to look; nobody is left out unless you choose it.
        </Text>
        {save.error && <ErrorCallout error={(save.error as ApiError).body} />}
        {latest.length > 0 && (
          <Callout.Root color="green" size="1">
            <Callout.Text>
              Saved in <code>reports/alps/</code>:{" "}
              {latest.map((f, i) => (
                <span key={f.name}>
                  {i > 0 && ", "}
                  <a href={f.url} target="_blank" rel="noreferrer">
                    {f.name}
                  </a>
                </span>
              ))}
            </Callout.Text>
          </Callout.Root>
        )}
      </Flex>
    </Card>
  );
}
