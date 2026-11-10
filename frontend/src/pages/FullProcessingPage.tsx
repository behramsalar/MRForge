import { CheckCircledIcon } from "@radix-ui/react-icons";
import { Button, Callout, Card, Flex, Grid, Heading, Switch, Text } from "@radix-ui/themes";
import { useState } from "react";
import { useOverview } from "../api/hooks";
import type { WorkspaceState } from "../api/types";
import { ConfirmProcessDialog } from "../components/ConfirmProcessDialog";
import { JobsPanel } from "../components/JobsPanel";
import { RouteMap } from "../components/RouteMap";
import { StageChips } from "../components/StageChips";
import { SubjectsTable } from "../components/SubjectsTable";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { GOALS, goalStages } from "../lib/goals";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

/** The default way to start work: choose a subject from the table, review the plan, confirm.
 * A subject that is already complete is not offered processing first: its results are. */
export function FullProcessingPage({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  const overview = useOverview(ws);
  const [picked, setPicked] = useState<string[]>([]);
  const [confirm, setConfirm] = useState(false);
  const [goalId, setGoalId] = useState("full");
  const [withArtifact, setWithArtifact] = useState(false);
  const rows = (overview.data?.subjects ?? []).filter((s) => s.n_files > 0);
  const chosen = picked.length === 1 ? picked[0] : undefined;
  const row = rows.find((s) => s.label === chosen);
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");
  const goal = GOALS.find((g) => g.id === goalId) ?? GOALS[0];
  const stagesOn = goalStages(goal, withArtifact);
  const dialogKey = `${goal.id}:${withArtifact}`;
  const pickedRows = rows.filter((s) => picked.includes(s.label));
  const jobs = (state?.jobs ?? []).filter((j) => j.subject === chosen);
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader
        title="Pipelines"
        description="Runs every processing stage for a subject, one after another: the recommended way to prepare data for analysis."
      />
      {overview.data && rows.length === 0 && (
        <EmptyState
          title="There is no data to process yet"
          text="Import your scans first; then come back here and press Process."
          action="Import scans"
          href={href(ws, "data")}
        />
      )}
      {rows.length > 0 && (
        <>
          <Flex direction="column" gap="2">
            <Heading as="h2" size={type.sectionTitle}>
              1. What do you want?
            </Heading>
            <Grid columns={{ initial: "1", sm: "2", lg: "5" }} gap="2">
              {GOALS.map((g) => (
                <button key={g.id} type="button" className="goal" aria-pressed={g.id === goal.id} onClick={() => setGoalId(g.id)}>
                  <span className="goal-title">{g.title}</span>
                  <span className="goal-text">{g.text}</span>
                </button>
              ))}
            </Grid>
            {goal.optionalArtifact && (
              <Text as="label" size={type.help}>
                <Flex gap="2" align="center">
                  <Switch size="1" checked={withArtifact} onCheckedChange={setWithArtifact} />
                  Include artifact rejection (you label the noise components; the pipeline waits for you)
                </Flex>
              </Text>
            )}
          </Flex>
          <RouteMap goal={goal} withArtifact={withArtifact} rows={pickedRows} />
          <Heading as="h2" size={type.sectionTitle}>
            2. Which subjects?
          </Heading>
          <Text size={type.help} color="gray">
            Tick one or more subjects. Several subjects are processed together, a few at a time.
          </Text>
          <SubjectsTable subjects={rows} selected={picked} onSelect={setPicked} multi />
          {picked.length > 1 && (
            <Card size="2" style={{ position: "sticky", bottom: "var(--space-3)", zIndex: 2, boxShadow: "var(--shadow-4)" }}>
              <Flex justify="between" align="center" gap={space.group} wrap="wrap">
                <Text weight="medium">{picked.length} subjects selected</Text>
                <Flex gap="2">
                  <Button variant="soft" color="gray" onClick={() => setPicked([])}>
                    Clear
                  </Button>
                  <Button size="3" disabled={busy} onClick={() => setConfirm(true)}>
                    Process {picked.length} subjects…
                  </Button>
                </Flex>
              </Flex>
            </Card>
          )}
        </>
      )}
      {row && (
        <Card size="3">
          <Flex direction="column" gap={space.group}>
            <Flex justify="between" align="center" gap={space.group} wrap="wrap">
              <Heading as="h2" size={type.sectionTitle}>
                {row.label}
              </Heading>
              <StageChips stages={row.stages} />
            </Flex>
            {row.complete ? (
              <Callout.Root color="green">
                <Callout.Icon>
                  <CheckCircledIcon />
                </Callout.Icon>
                <Flex align="center" justify="between" gap={space.group} wrap="wrap" style={{ width: "100%" }}>
                  <Text>{row.label} is already processed.</Text>
                  <Flex gap="2">
                    <Button asChild>
                      <a href={href(ws, "subject", row.label, "results")}>See the results</a>
                    </Button>
                    <Button variant="soft" color="gray" disabled={busy} onClick={() => setConfirm(true)}>
                      Process again…
                    </Button>
                  </Flex>
                </Flex>
              </Callout.Root>
            ) : (
              <Flex gap={space.group} align="center" wrap="wrap">
                <Button size="3" disabled={busy} onClick={() => setConfirm(true)}>
                  Process {row.label}…
                </Button>
                <Button size="3" variant="soft" color="gray" asChild>
                  <a href={href(ws, "subject", row.label)}>Open the subject page</a>
                </Button>
              </Flex>
            )}
            <Text size={type.help} color="gray">
              You will see exactly what runs, with the settings, before anything starts. To run one stage on its own, use the
              entries under "Single steps" in the sidebar.
            </Text>
          </Flex>
        </Card>
      )}
      {row && <ConfirmProcessDialog key={dialogKey} ws={ws} subject={row.label} stagesOn={stagesOn} open={confirm} onOpenChange={setConfirm} />}
      {picked.length > 1 && (
        <ConfirmProcessDialog key={dialogKey} ws={ws} subject={picked[0]} subjects={picked} stagesOn={stagesOn} open={confirm} onOpenChange={setConfirm} />
      )}
      {row && <JobsPanel ws={ws} jobs={jobs} busy={busy} />}
    </Flex>
  );
}
