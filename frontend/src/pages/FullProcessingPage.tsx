import { ArrowRightIcon } from "@radix-ui/react-icons";
import { Button, Card, Flex, Heading, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { api } from "../api/client";
import { call } from "../api/call";
import { useOverview } from "../api/hooks";
import type { FullOptions, StagePlan } from "../api/types";
import { JobsPanel } from "../components/JobsPanel";
import { PresetBar } from "../components/PresetBar";
import { ReviewStartDialog } from "../components/ReviewStartDialog";
import { StageTile } from "../components/StageTile";
import { StageSettingsPanel } from "../components/StageSettingsPanel";
import { SubjectsTable } from "../components/SubjectsTable";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import type { WorkspaceState } from "../api/types";
import { href } from "../lib/router";
import { DEFAULTS, STAGE_GROUPS, settingsChanged, signature, stageCounts, usePlan } from "../lib/processOptions";
import { STAGE_PAGES } from "../shell/nav";
import { space, type } from "../theme/tokens";

const HAS_SETTINGS = new Set(["anatomical", "functional", "artifact_rejection", "connectivity", "diffusion"]);
const FALLBACK_LABEL: Record<string, string> = {
  anatomical: "Structural (T1)",
  functional: "Functional",
  artifact_rejection: "Artifact rejection",
  standard_space: "Standard space",
  connectivity: "Connectivity (ROI to ROI)",
  diffusion: "Diffusion (ALPS)",
};
const GROUP_HELP: Record<string, string> = {
  pre: "Make the scans clean and comparable. The stages run in this order.",
  analysis: "Questions asked of the cleaned data. Needs the functional data in standard space.",
  diffusion: "A separate pipeline for diffusion scans. It needs none of the other stages.",
};

/** The chosen settings of a stage, one per line, without repeats (a stage planned for several runs lists each once). */
const paramsOf = (s?: StagePlan) => {
  const seen = new Set<string>();
  return (s?.items ?? [])
    .flatMap((i) => i.settings)
    .filter((x) => !seen.has(`${x.name}:${x.value}`) && !!seen.add(`${x.name}:${x.value}`))
    .map((x) => ({ name: x.name, value: String(x.value) }));
};

/** The Process page: stages in the order a methods section describes them, each with a switch, a
 * one-line summary and its settings one click away; presets for saving a whole setup; subjects
 * below; the start bar stays in view once someone is ticked. */
export function FullProcessingPage({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  const overview = useOverview(ws);
  const [picked, setPicked] = useState<string[]>([]);
  const [opts, setOpts] = useState<FullOptions>({ ...DEFAULTS });
  const [presetId, setPresetId] = useState("custom");
  const [panel, setPanel] = useState<string | null>(null);
  const [review, setReview] = useState(false);
  const rows = (overview.data?.subjects ?? []).filter((s) => s.n_files > 0);
  const chosenRows = rows.filter((s) => picked.includes(s.label));
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");
  const presets = useQuery({ queryKey: ["presets"], queryFn: () => call(api.GET("/api/presets")) });
  const chosenPreset = (presets.data ?? []).find((x) => x.id === presetId);
  // The preset is recorded with the run only while the choices still equal it.
  const presetName = chosenPreset && signature(chosenPreset.options as never) === signature(opts) ? chosenPreset.name : undefined;
  // With nobody ticked the first subject is asked, only to learn the stages and their defaults.
  const planSubjects = picked.length > 0 ? picked : rows[0] ? [rows[0].label] : [];
  const plan = usePlan(ws, opts, planSubjects, rows.length > 0, presetName);
  const stages = plan.data?.stages ?? [];
  const stageOf = (id: string) => stages.find((s) => s.id === id);
  const enabledOf = (id: string) => stageOf(id)?.enabled ?? opts.stages?.[id] ?? false;
  const setStage = (id: string, on: boolean) => setOpts({ ...opts, stages: { ...opts.stages, [id]: on } });
  const jobs = (state?.jobs ?? []).filter((j) => picked.length === 1 && j.subject === picked[0]);
  const doneEarlier = Object.fromEntries(STAGE_GROUPS.flatMap((g) => g.stages).map((id) => [id, stageCounts(id, chosenRows).done]));
  const included = stages.filter((s) => s.enabled && s.can_run);
  const statusOf = (id: string): string | undefined => {
    if (picked.length === 0) return undefined;
    const c = stageCounts(id, chosenRows);
    if (c.done === 0) return undefined;
    return picked.length === 1 ? "Done earlier" : `${c.done} of ${picked.length} done earlier`;
  };
  const stagePageHref = (id: string) => {
    if (id === "artifact_rejection") return href(ws, "quality", "artifacts");
    const sp = STAGE_PAGES.find((x) => x.stage === id);
    return sp ? href(ws, "process", sp.extra) : undefined;
  };
  const renderGroup = (g: (typeof STAGE_GROUPS)[number]) => (
    <div key={g.id} className="tile-group">
      <Flex direction="column">
        <Heading as="h2" size={type.sectionTitle}>
          {g.title}
        </Heading>
        <Text size={type.caption} color="gray" className="tile-group-help">
          {GROUP_HELP[g.id]}
        </Text>
      </Flex>
      <div className="tiles">
        {g.stages.map((id, i) => {
          const s = stageOf(id);
          return (
            <Fragment key={id}>
              {i > 0 && g.id === "pre" && <ArrowRightIcon className="tile-arrow" aria-hidden />}
              <StageTile
                label={s?.label ?? FALLBACK_LABEL[id]}
                plan={picked.length > 0 ? s : undefined}
                enabled={enabledOf(id)}
                onToggle={(on) => setStage(id, on)}
                description={s?.description ?? ""}
                params={paramsOf(s)}
                status={statusOf(id)}
                hasSettings={HAS_SETTINGS.has(id)}
                changed={settingsChanged(id, opts)}
                onSettings={() => setPanel(id)}
                pageHref={stagePageHref(id)}
              />
            </Fragment>
          );
        })}
      </div>
    </div>
  );
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader
        title="Process"
        description="Switch on the stages you want, adjust their settings if needed, choose subjects and start."
      />
      {overview.data && rows.length === 0 && (
        <EmptyState
          title="There is no data to process yet"
          text="Import your scans first; then come back here and press Process."
          action="Import scans"
          href={href(ws, "import")}
        />
      )}
      {rows.length > 0 && (
        <>
          <PresetBar opts={opts} onChange={setOpts} presetId={presetId} onPresetId={setPresetId} />
          <Flex direction="column" gap="3">
            {renderGroup(STAGE_GROUPS[0])}
            <div className="tile-pair">
              {STAGE_GROUPS.slice(1).map((g) => renderGroup(g))}
            </div>
          </Flex>
          <Heading as="h2" size={type.sectionTitle}>
            Subjects
          </Heading>
          <Text size={type.help} color="gray" style={{ marginTop: "calc(var(--space-2) * -1)" }}>
            Tick one or more. Several subjects are processed together, a few at a time, with the same settings.
          </Text>
          <SubjectsTable subjects={rows} selected={picked} onSelect={setPicked} multi />
          {jobs.length > 0 && <JobsPanel ws={ws} jobs={jobs} busy={busy} />}
          {picked.length > 0 && (
            <Card size="2" style={{ position: "sticky", bottom: "var(--space-3)", zIndex: 2, boxShadow: "var(--shadow-4)" }}>
              <Flex justify="between" align="center" gap={space.group} wrap="wrap">
                <Flex direction="column" style={{ minWidth: 0 }}>
                  <Text weight="medium">
                    {picked.length === 1 ? picked[0] : `${picked.length} subjects`}
                  </Text>
                  <Text size={type.caption} color="gray">
                    {included.length > 0 ? included.map((s) => s.label).join(", ") : "No stage switched on"}
                  </Text>
                </Flex>
                <Flex gap="2">
                  <Button variant="soft" color="gray" onClick={() => setPicked([])}>
                    Clear
                  </Button>
                  <Button size="3" disabled={busy || !plan.data?.can_start} onClick={() => setReview(true)}>
                    Review and start…
                  </Button>
                </Flex>
              </Flex>
            </Card>
          )}
        </>
      )}
      <StageSettingsPanel
        stageId={panel}
        label={panel ? (stageOf(panel)?.label ?? FALLBACK_LABEL[panel]) : ""}
        description={panel ? stageOf(panel)?.description : undefined}
        opts={opts}
        setOpts={setOpts}
        onClose={() => setPanel(null)}
      />
      <ReviewStartDialog
        ws={ws}
        open={review}
        onOpenChange={setReview}
        opts={opts}
        subjects={picked}
        preset={presetName}
        stages={stages}
        canStart={!!plan.data?.can_start}
        steps={plan.data?.steps ?? 0}
        batch={plan.data?.batch ?? null}
        doneEarlier={doneEarlier}
      />
    </Flex>
  );
}
