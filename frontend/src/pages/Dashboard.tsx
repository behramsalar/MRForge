import { ArchiveIcon, CheckCircledIcon, CrossCircledIcon, PersonIcon } from "@radix-ui/react-icons";
import { Button, Card, Flex, Grid, Heading, Text } from "@radix-ui/themes";
import { useSubjects } from "../api/hooks";
import type { WorkspaceState } from "../api/types";
import { latestJobs } from "../components/JobsPanel";
import { EmptyState, PageHeader, StatCard } from "../components/ui/Layout";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

/** First version of the dashboard (O1); the subjects-by-stage table and pipeline stepper follow. */
export function Dashboard({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  const subjects = useSubjects(ws);
  const jobs = latestJobs(state?.jobs ?? []);
  const failed = jobs.filter((j) => j.status === "Failed" || j.status === "Interrupted").length;
  const done = jobs.filter((j) => j.status === "Completed").length;
  const imports = state?.imports.length ?? 0;
  if (state && subjects.data && subjects.data.length === 0 && imports === 0) {
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
        <StatCard label="Subjects" value={subjects.data?.length ?? "-"} icon={<PersonIcon width={22} height={22} />} />
        <StatCard label="Imports" value={imports} icon={<ArchiveIcon width={22} height={22} />} />
        <StatCard label="Steps finished" value={done} color="green" icon={<CheckCircledIcon width={22} height={22} />} />
        <StatCard
          label="Need attention"
          value={failed}
          color={failed ? "red" : "gray"}
          icon={<CrossCircledIcon width={22} height={22} />}
        />
      </Grid>
      <Card size="3">
        <Flex direction="column" gap={space.group}>
          <Heading size={type.sectionTitle}>Next steps</Heading>
          <Text color="gray" size={type.body}>
            Import more scans, run anatomical and functional processing, then look at the results in the viewer.
          </Text>
        </Flex>
      </Card>
    </Flex>
  );
}
