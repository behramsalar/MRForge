import {
  ArchiveIcon,
  CheckCircledIcon,
  ExclamationTriangleIcon,
  LightningBoltIcon,
  PersonIcon,
} from "@radix-ui/react-icons";
import { Badge, Button, Card, Flex, Grid, Heading, Table, Text } from "@radix-ui/themes";
import type { WorkspaceState } from "../api/types";
import { useOverview } from "../api/hooks";
import { PipelineStepper } from "../components/PipelineStepper";
import { StageBadge, StatusBadge } from "../components/ui/Badges";
import { EmptyState, PageHeader, StatCard } from "../components/ui/Layout";
import { elapsed, when } from "../lib/labels";
import { href } from "../lib/router";
import { useTick } from "../api/hooks";
import { useWorkspace } from "../shell/WorkspaceContext";
import { space, type } from "../theme/tokens";

/** Where this study stands: totals, the pipeline, every subject, what runs now, what ran. */
export function Dashboard({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  const overview = useOverview(ws);
  const { state: live } = useWorkspace();
  const o = overview.data;
  useTick(!!o && o.running_now.length > 0);
  void state;

  if (o && o.subjects_total === 0 && (live?.imports.length ?? 0) === 0) {
    return (
      <Flex direction="column" gap={space.section}>
        <PageHeader title={ws} description="This workspace is empty." />
        <EmptyState
          icon={<ArchiveIcon width={32} height={32} />}
          title="Start your first import"
          text="Choose the folder or ZIP with your scanner files. MRForge reads them, shows what it found and asks only about what it cannot decide itself."
          action="Import scans"
          href={href(ws, "data")}
        />
      </Flex>
    );
  }
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader
        title={ws}
        description="Where this study stands."
        actions={
          <Button size="3" asChild>
            <a href={href(ws, "process")}>Process data</a>
          </Button>
        }
      />
      <Grid columns={{ initial: "1", sm: "2", lg: "4" }} gap={space.group}>
        <StatCard label="Subjects" value={o?.subjects_total ?? "-"} color="indigo" icon={<PersonIcon width={22} height={22} />} />
        <StatCard
          label="Processed"
          value={o?.processed ?? "-"}
          hint={o && o.subjects_total ? `${Math.round((100 * o.processed) / o.subjects_total)}% of subjects` : undefined}
          color="green"
          icon={<CheckCircledIcon width={22} height={22} />}
        />
        <StatCard
          label="Need attention"
          value={o?.needs_attention ?? "-"}
          color={o?.needs_attention ? "red" : "gray"}
          icon={<ExclamationTriangleIcon width={22} height={22} />}
        />
        <StatCard
          label="Running now"
          value={o?.running ?? "-"}
          color={o?.running ? "orange" : "gray"}
          icon={<LightningBoltIcon width={22} height={22} />}
        />
      </Grid>

      <Grid columns={{ initial: "1", lg: "3" }} gap={space.group} align="start">
        <Flex direction="column" gap={space.group} style={{ gridColumn: "span 2" }}>
          {o && <PipelineStepper stages={o.stages} />}
          <Card size="3">
            <Flex direction="column" gap={space.group}>
              <Heading as="h2" size={type.sectionTitle}>Subjects</Heading>
              <Table.Root>
                <Table.Header>
                  <Table.Row>
                    <Table.ColumnHeaderCell>Subject</Table.ColumnHeaderCell>
                    <Table.ColumnHeaderCell>Files</Table.ColumnHeaderCell>
                    <Table.ColumnHeaderCell>Anatomical</Table.ColumnHeaderCell>
                    <Table.ColumnHeaderCell>Functional</Table.ColumnHeaderCell>
                    <Table.ColumnHeaderCell>Last activity</Table.ColumnHeaderCell>
                    <Table.ColumnHeaderCell />
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {(o?.subjects ?? []).map((s) => (
                    <Table.Row key={s.label}>
                      <Table.RowHeaderCell>{s.label}</Table.RowHeaderCell>
                      <Table.Cell>{s.n_files}</Table.Cell>
                      <Table.Cell>
                        <StageBadge state={s.anatomical.state} detail={s.anatomical.detail} />
                      </Table.Cell>
                      <Table.Cell>
                        <StageBadge state={s.functional.state} detail={s.functional.detail} />
                      </Table.Cell>
                      <Table.Cell>
                        {s.last_activity ? (
                          <Flex direction="column">
                            <Text size={type.help}>{when(s.last_activity)}</Text>
                            {s.last_activity_by && (
                              <Text size={type.caption} color="gray">
                                {s.last_activity_by}
                              </Text>
                            )}
                          </Flex>
                        ) : (
                          <Text size={type.help} color="gray">
                            -
                          </Text>
                        )}
                      </Table.Cell>
                      <Table.Cell>
                        <Button asChild size="1" variant="soft" color="gray">
                          <a href={href(ws, "viewer", s.label)}>View</a>
                        </Button>
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table.Root>
            </Flex>
          </Card>
        </Flex>

        <Flex direction="column" gap={space.group}>
          <Card size="3">
            <Flex direction="column" gap={space.group}>
              <Heading as="h2" size={type.sectionTitle}>Running now</Heading>
              {o && o.running_now.length === 0 && (
                <Text size={type.help} color="gray">
                  Nothing is running.
                </Text>
              )}
              {(o?.running_now ?? []).map((r) => (
                <Flex key={r.title} direction="column" gap="1">
                  <Text size={type.help} weight="medium">
                    {r.title}
                  </Text>
                  <Text size={type.caption} color="gray">
                    {elapsed(r.started, null)}
                    {r.started_by ? ` · ${r.started_by}` : ""}
                  </Text>
                </Flex>
              ))}
            </Flex>
          </Card>
          <Card size="3">
            <Flex direction="column" gap={space.group}>
              <Heading as="h2" size={type.sectionTitle}>Recent activity</Heading>
              {o && o.recent.length === 0 && (
                <Text size={type.help} color="gray">
                  Nothing has happened yet.
                </Text>
              )}
              {(o?.recent ?? []).map((a, i) => (
                <Flex key={`${a.title}-${i}`} justify="between" align="start" gap={space.group}>
                  <Flex direction="column" style={{ minWidth: 0 }}>
                    <Text size={type.help}>{a.title}</Text>
                    <Text size={type.caption} color="gray">
                      {when(a.when)}
                      {a.started_by ? ` · ${a.started_by}` : ""}
                    </Text>
                  </Flex>
                  <StatusBadge status={a.status} />
                </Flex>
              ))}
              {o && o.recent.length > 0 && (
                <a href={href(ws, "jobs")}>
                  <Text size={type.help}>See all jobs</Text>
                </a>
              )}
            </Flex>
          </Card>
        </Flex>
      </Grid>
      <Badge style={{ display: "none" }}>{overview.isFetching ? "refreshing" : ""}</Badge>
    </Flex>
  );
}
