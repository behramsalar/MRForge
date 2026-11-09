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

/** The ROI-to-ROI matrices of every recording in the workspace, and the index file with the full path of each participant's files.
 * Every number is read from what the processing recorded; flags only warn. */
export function ConnectivityResultsTable({ ws }: { ws: string }) {
  const client = useQueryClient();
  const [leaveOut, setLeaveOut] = useState(false);
  const rows = useQuery({
    queryKey: ["ws", ws, "roi-results"],
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/roi-results", { params: { path: { ws_id: ws } } })),
  });
  const saved = useQuery({
    queryKey: ["ws", ws, "roi-results", "exports"],
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/roi-results/exports", { params: { path: { ws_id: ws } } })),
  });
  const save = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/roi-results/export", {
          params: { path: { ws_id: ws }, query: { leave_out_excluded: leaveOut } },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["ws", ws, "roi-results", "exports"] }),
  });
  const data = rows.data ?? [];
  if (rows.error) return <ErrorCallout error={(rows.error as ApiError).body} />;
  const latest = (save.data ?? saved.data ?? []).slice(0, 2);
  return (
    <Card size="3">
      <Flex direction="column" gap={space.group}>
        <Flex justify="between" align="center" wrap="wrap" gap={space.group}>
          <Heading as="h2" size={type.sectionTitle}>
            Connectivity results
          </Heading>
          <Flex gap={space.group} align="center" wrap="wrap">
            <Text as="label" size={type.help}>
              <Flex gap="2" align="center">
                <Checkbox checked={leaveOut} onCheckedChange={(v) => setLeaveOut(v === true)} />
                Leave out subjects I excluded
              </Flex>
            </Text>
            <Button disabled={data.length === 0 || save.isPending} onClick={() => save.mutate()}>
              <DownloadIcon /> Save list of files (CSV)
            </Button>
          </Flex>
        </Flex>
        {data.length === 0 ? (
          <Text size={type.help} color="gray">
            No matrices yet. Run the Connectivity stage for a subject and its results appear here.
          </Text>
        ) : (
          <Table.Root size="1" variant="surface">
            <Table.Header>
              <Table.Row>
                <Table.ColumnHeaderCell>Subject</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Recording</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Atlas</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Regions</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Volumes</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Mean coverage</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Your decision</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Flags</Table.ColumnHeaderCell>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {data.map((r) => (
                <Table.Row key={`${r.subject}${r.session ?? ""}${r.recording}${r.atlas}`}>
                  <Table.RowHeaderCell>
                    <a href={href(ws, "subject", r.subject)}>{r.subject}</a>
                    {r.session ? ` ${r.session}` : ""}
                  </Table.RowHeaderCell>
                  <Table.Cell>
                    <Text size={type.help}>{r.recording}</Text>
                  </Table.Cell>
                  <Table.Cell>
                    <Tooltip content={r.averaging}>
                      <Text size={type.help}>{r.atlas_name}</Text>
                    </Tooltip>
                  </Table.Cell>
                  <Table.Cell>{r.regions}</Table.Cell>
                  <Table.Cell>{r.volumes}</Table.Cell>
                  <Table.Cell>{r.mean_coverage == null ? "" : `${Math.round(r.mean_coverage * 100)}%`}</Table.Cell>
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
          Values are those recorded when each run was processed; the matrices are plain numbers, ready for NBS-type tools. Flags are only a prompt to look; nobody is left out unless you choose it.
        </Text>
        {save.error && <ErrorCallout error={(save.error as ApiError).body} />}
        {latest.length > 0 && (
          <Callout.Root color="green" size="1">
            <Callout.Text>
              Saved in <code>reports/roi/</code>:{" "}
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
