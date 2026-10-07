import {
  ArchiveIcon,
  CheckCircledIcon,
  ExclamationTriangleIcon,
  LightningBoltIcon,
  PersonIcon,
} from "@radix-ui/react-icons";
import { Badge, Button, Callout, Card, Flex, Grid, Heading, Text } from "@radix-ui/themes";
import type { WorkspaceState } from "../api/types";
import { useOverview } from "../api/hooks";
import { PipelineStepper } from "../components/PipelineStepper";
import { StatusBadge } from "../components/ui/Badges";
import { AnalysisReadyCard } from "../components/AnalysisReadyCard";
import { SubjectsTable } from "../components/SubjectsTable";
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
      {o && o.review.length > 0 && (
        <Callout.Root color="amber">
          <Callout.Icon>
            <PersonIcon />
          </Callout.Icon>
          <Flex align="center" justify="between" gap={space.group} wrap="wrap" style={{ width: "100%" }}>
            <Flex direction="column">
              <Text weight="bold">Needs your review</Text>
              {o.review.map((r, i) => (
                <Text key={i} size={type.help}>
                  {r.what} ({r.subject})
                </Text>
              ))}
            </Flex>
            <Button asChild>
              <a href={`#/w/${encodeURIComponent(ws)}/${o.review[0].page}`}>Open the review</a>
            </Button>
          </Flex>
        </Callout.Root>
      )}
      <Grid columns={{ initial: "1", sm: "2", lg: "4" }} gap={space.group}>
        <StatCard label="Subjects" value={o?.subjects_total ?? "-"} icon={<PersonIcon width={22} height={22} />} />
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
          {o && <AnalysisReadyCard ws={ws} subjectsWithRuns={o.stages.find((x) => x.id === "preprocessing")?.total ?? 0} />}
          <Card size="3">
            <Flex direction="column" gap={space.group}>
              <Heading as="h2" size={type.sectionTitle}>Subjects</Heading>
              <SubjectsTable subjects={o?.subjects ?? []} onOpen={(l) => (location.hash = href(ws, "subject", l))} />
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
