import { ArrowLeftIcon } from "@radix-ui/react-icons";
import { Badge, Button, Callout, Card, Flex, Grid, Heading, SegmentedControl, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { call } from "../api/call";
import { useOverview } from "../api/hooks";
import type { StageChip, WorkspaceState } from "../api/types";
import { ConfirmProcessDialog } from "../components/ConfirmProcessDialog";
import { JobsPanel } from "../components/JobsPanel";
import { QcPanel } from "../components/QcPanel";
import { QualityDecisionCard } from "../components/QualityDecisionCard";
import { StageBadge } from "../components/ui/Badges";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

// What each stage card offers: which stage a "Run" starts, and a page to look at.
const STAGE_ACTIONS: Record<string, { stage: string; look?: [string, string?]; lookLabel?: string }> = {
  anatomical: { stage: "anatomical", look: ["process", "anat"], lookLabel: "Open the page" },
  preprocessing: { stage: "functional", look: ["process", "func"], lookLabel: "Open the page" },
  artifact_rejection: { stage: "artifact_rejection", look: ["process", "ica"], lookLabel: "Open the review" },
  standard_space: { stage: "standard_space", look: ["process", "mni"], lookLabel: "Open the page" },
};

function StageCard({
  chip,
  busy,
  onRun,
  ws,
}: {
  chip: StageChip;
  busy: boolean;
  onRun: (stage: string) => void;
  ws: string;
}) {
  const action = STAGE_ACTIONS[chip.id];
  const possible = chip.state !== "unavailable";
  return (
    <Card size="2">
      <Flex direction="column" gap="2" style={{ height: "100%" }}>
        <Text weight="bold">{chip.label}</Text>
        <Flex gap="2" align="center" wrap="wrap">
          <StageBadge state={chip.state} detail={chip.detail} />
        </Flex>
        {action && possible && (
          <Flex gap="2" wrap="wrap" mt="auto">
            <Button size="1" variant={chip.state === "done" ? "soft" : "solid"} color={chip.state === "done" ? "gray" : undefined} disabled={busy} onClick={() => onRun(action.stage)}>
              {chip.state === "done" ? "Run again…" : "Run…"}
            </Button>
            {action.look && (
              <Button size="1" variant="ghost" asChild>
                <a href={href(ws, action.look[0], action.look[1])}>{action.lookLabel}</a>
              </Button>
            )}
          </Flex>
        )}
      </Flex>
    </Card>
  );
}

function Files({ ws, subject }: { ws: string; subject: string }) {
  const images = useQuery({
    queryKey: ["ws", ws, "images", subject],
    queryFn: () =>
      call(api.GET("/api/workspaces/{ws_id}/subjects/{label}/images", { params: { path: { ws_id: ws, label: subject } } })),
  });
  const groups = new Map<string, NonNullable<typeof images.data>>();
  for (const i of images.data ?? []) groups.set(i.group, [...(groups.get(i.group) ?? []), i]);
  if (!images.data?.length) return null;
  return (
    <Flex direction="column" gap={space.group}>
      <Heading as="h2" size={type.sectionTitle}>
        Images
      </Heading>
      {[...groups.entries()].map(([group, list]) => (
        <Card key={group}>
          <Flex direction="column" gap="2">
            <Text weight="bold">{group}</Text>
            {list.map((i) => (
              <Flex key={i.relpath} justify="between" align="center" gap={space.group}>
                <Flex direction="column" style={{ minWidth: 0 }}>
                  <Text size={type.help}>{i.name}</Text>
                  <Text size={type.caption} color="gray" style={{ wordBreak: "break-all" }}>
                    {i.relpath.split("/").pop()}
                  </Text>
                </Flex>
                <Button size="1" variant="soft" color="gray" asChild>
                  <a href={href(ws, "viewer", subject, i.relpath)}>Open in viewer</a>
                </Button>
              </Flex>
            ))}
          </Flex>
        </Card>
      ))}
    </Flex>
  );
}

/** One subject: where it stands stage by stage, the head-motion numbers, what to do next, and
 * (Results tab) everything recorded about its results. Reports will replace the Results tab. */
export function SubjectPage({ ws, label, tab, state }: { ws: string; label?: string; tab?: string; state: WorkspaceState | null }) {
  const overview = useOverview(ws);
  const [run, setRun] = useState<string | null | "all">(null);
  const row = overview.data?.subjects.find((s) => s.label === label);
  const ready = useQuery({
    queryKey: ["ws", ws, "analysis-ready"],
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/analysis-ready", { params: { path: { ws_id: ws } } })),
  });
  const readyRows = (ready.data?.rows ?? []).filter((r) => r.subject === label);
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");
  const current = tab === "results" ? "results" : "overview";
  const go = (t: string) => {
    location.hash = href(ws, "subject", label ?? "", t === "overview" ? undefined : t);
  };
  if (!label || (overview.data && !row)) {
    return (
      <EmptyState title="No such subject" text="This subject is not in the workspace." action="Back to the dashboard" href={href(ws, "dashboard")} />
    );
  }
  const jobs = (state?.jobs ?? []).filter((j) => j.subject === label);
  const waiting = row?.stages.find((c) => c.state === "review");
  return (
    <Flex direction="column" gap={space.section}>
      <Button size="1" variant="ghost" asChild style={{ alignSelf: "flex-start" }}>
        <a href={href(ws, "dashboard")}>
          <ArrowLeftIcon /> All subjects
        </a>
      </Button>
      <PageHeader
        title={label}
        description={
          (row?.complete ? "Processing of this subject is complete." : "Where this subject stands, and what is left to do.") +
          (row?.preset ? ` Last processed with the preset "${row.preset}".` : "")
        }
        actions={
          <Button size="3" variant={row?.complete ? "soft" : "solid"} color={row?.complete ? "gray" : undefined} disabled={busy} onClick={() => setRun("all")}>
            {row?.complete ? "Process everything again…" : `Process ${label}…`}
          </Button>
        }
      />
      <SegmentedControl.Root value={current} onValueChange={go} style={{ alignSelf: "flex-start" }}>
        <SegmentedControl.Item value="overview">Overview</SegmentedControl.Item>
        <SegmentedControl.Item value="results">Results</SegmentedControl.Item>
      </SegmentedControl.Root>

      {current === "overview" && row && (
        <>
          {waiting && (
            <Callout.Root color="amber">
              <Flex align="center" justify="between" gap={space.group} wrap="wrap" style={{ width: "100%" }}>
                <Text>Processing waits for your decision on the components.</Text>
                <Button asChild>
                  <a href={href(ws, "process", "ica")}>Open the review</a>
                </Button>
              </Flex>
            </Callout.Root>
          )}
          <Grid columns={{ initial: "1", sm: "2", lg: "4" }} gap={space.group}>
            {row.stages
              .filter((c) => c.id !== "import")
              .map((c) => (
                <StageCard key={c.id} chip={c} busy={busy} ws={ws} onRun={(stage) => setRun(stage)} />
              ))}
          </Grid>
          <QualityDecisionCard ws={ws} row={row} />
          <Card size="2">
            <Flex direction="column" gap="1">
              <Heading as="h2" size={type.sectionTitle}>
                Head motion
              </Heading>
              {row.qc ? (
                <Text size={type.help}>
                  Mean framewise displacement {row.qc.fd_mean_mm} mm, largest {row.qc.fd_max_mm} mm;{" "}
                  {row.qc.volumes_above} of {row.qc.n_volumes} volumes above {row.qc.threshold_mm} mm.
                </Text>
              ) : (
                <Text size={type.help} color="gray">
                  Not measured yet (functional preprocessing has not finished).
                </Text>
              )}
              <Text size={type.caption} color="gray">
                Numbers to look at. MRForge never excludes a subject by itself.
              </Text>
            </Flex>
          </Card>
          <Card size="2">
            <Flex direction="column" gap="1">
              <Heading as="h2" size={type.sectionTitle}>
                For group analysis
              </Heading>
              {readyRows.length === 0 ? (
                <Text size={type.help} color="gray">
                  Not yet: the final file appears here when standard space has finished.
                </Text>
              ) : (
                readyRows.map((r) => (
                  <Flex key={r.file} direction="column">
                    <Text size={type.help}>
                      <Badge color="green" variant="soft">
                        Analysis-ready
                      </Badge>{" "}
                      {r.recording}: {Object.entries(r.settings).filter(([k]) => ["Noise removal", "Smoothing (mm)"].includes(k)).map(([k, v]) => `${k} ${v}`).join(" · ")}
                    </Text>
                    <Text size={type.caption} color="gray" style={{ wordBreak: "break-all" }}>
                      {r.file}
                    </Text>
                  </Flex>
                ))
              )}
            </Flex>
          </Card>
          <JobsPanel ws={ws} jobs={jobs} busy={busy} />
        </>
      )}

      {current === "results" && (
        <>
          <Callout.Root color="gray" size="1">
            <Callout.Text>
              This is what MRForge recorded for {label}: quality checks, numbers and images. A full report will replace this page in
              a later version.
            </Callout.Text>
          </Callout.Root>
          {row && !row.stages.some((c) => c.state === "done") && (
            <Badge color="gray" variant="soft" style={{ alignSelf: "flex-start" }}>
              Nothing has finished for this subject yet.
            </Badge>
          )}
          <QcPanel ws={ws} subject={label} />
          <Files ws={ws} subject={label} />
        </>
      )}

      {run === "all" && <ConfirmProcessDialog ws={ws} subject={label} open onOpenChange={(o) => !o && setRun(null)} />}
      {run && run !== "all" && (
        <ConfirmProcessDialog ws={ws} subject={label} open onOpenChange={(o) => !o && setRun(null)} onlyStage={run} />
      )}
    </Flex>
  );
}
