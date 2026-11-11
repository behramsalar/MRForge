import { Badge, Button, Callout, Card, Checkbox, Dialog, Flex, Select, Text, TextArea, TextField } from "@radix-ui/themes";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { FullOptions, Preset, StagePlan } from "../api/types";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";
import { StageSettings } from "./StageSettings";
import { DEFAULTS, STAGE_IDS, signature } from "../lib/processOptions";

const STAGE_HAS_SETTINGS = new Set(["anatomical", "functional", "artifact_rejection", "connectivity", "diffusion"]);


function StageCard({
  stage,
  onToggle,
  settings,
  open,
  onOpen,
}: {
  stage: StagePlan;
  onToggle: (enabled: boolean) => void;
  settings?: ReactNode;
  open: boolean;
  onOpen: (open: boolean) => void;
}) {
  const active = stage.enabled && stage.can_run;
  const chips = active ? stage.items.flatMap((item) => item.settings.map((x) => `${x.name}: ${x.value}`)) : [];
  return (
    <Card variant="surface" style={{ opacity: stage.can_run ? 1 : 0.7, flexShrink: 0 }}>
      <Flex direction="column" gap="2">
        <Flex align="center" gap={space.inline}>
          <Text as="label" size={type.body}>
            <Flex gap={space.inline} align="center">
              <Checkbox checked={active} disabled={!stage.can_run} onCheckedChange={(v) => onToggle(v === true)} />
              <Text weight="bold">{stage.label}</Text>
            </Flex>
          </Text>
          {stage.already_done && (
            <Badge color="green" variant="soft">
              Done earlier: not repeated if unchanged
            </Badge>
          )}
          {settings && (stage.can_run || open) && (
            <Button
              size="1"
              variant="ghost"
              style={{ marginLeft: "auto" }}
              aria-expanded={open}
              onClick={() => onOpen(!open)}
            >
              {open ? "Hide settings" : "Edit settings"}
            </Button>
          )}
        </Flex>
        <Text size={type.help} color="gray">
          {stage.can_run ? stage.description : `Not possible: ${stage.reason}`}
        </Text>
        {active &&
          stage.items.map(
            (item) =>
              item.note && (
                <Text key={item.title} size={type.caption} color="orange">
                  {item.note}
                </Text>
              ),
          )}
        {chips.length > 0 && (
          <Flex gap="1" wrap="wrap">
            {chips.map((c) => (
              <Badge key={c} color="gray" variant="soft" size="1">
                {c}
              </Badge>
            ))}
          </Flex>
        )}
        {settings && (stage.can_run || open) && open && (
          <Flex direction="column" gap={space.group} pt="2" style={{ borderTop: "1px solid var(--gray-a5)" }}>
            {settings}
          </Flex>
        )}
      </Flex>
    </Card>
  );
}

/** The confirmation before full processing: what will run, with the default settings, anything
 * left out and why, and a way to change the settings. Stages come from the plan, so a new
 * stage shows up here without changes to this dialog. */

export function ConfirmProcessDialog({
  ws,
  subject,
  open,
  onOpenChange,
  onStarted,
  onlyStage,
  stagesOn,
  subjects,
}: {
  ws: string;
  subject: string;
  onlyStage?: string; // run just this stage (the others are unticked; earlier results are used)
  stagesOn?: string[]; // the stages ticked when the dialog opens (a goal from the Process page); can still be changed
  subjects?: string[]; // several subjects at once (a batch): the same choices for all of them
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted?: () => void;
}) {
  const client = useQueryClient();
  const [opts, setOpts] = useState<FullOptions>({
    ...DEFAULTS,
    subject,
    stages: onlyStage
      ? Object.fromEntries(STAGE_IDS.map((id) => [id, id === onlyStage]))
      : stagesOn
        ? Object.fromEntries(STAGE_IDS.map((id) => [id, stagesOn.includes(id)]))
        : {},
  });
  const [openCards, setOpenCards] = useState<Set<string>>(new Set());
  const presets = useQuery({ queryKey: ["presets"], queryFn: () => call(api.GET("/api/presets")), enabled: open });
  const [presetId, setPresetId] = useState<string>("custom");
  const chosenPreset = (presets.data ?? []).find((x) => x.id === presetId);
  // The preset is recorded with the run only while the choices still equal it.
  const presetName = chosenPreset && signature(chosenPreset.options as never) === signature(opts) ? chosenPreset.name : undefined;
  const applyPreset = (id: string) => {
    setPresetId(id);
    const x = presets.data?.find((q) => q.id === id);
    if (!x) return;
    setOpts({
      ...opts,
      stages: onlyStage || stagesOn ? opts.stages : x.options.stages,
      anatomical: x.options.anatomical,
      functional: x.options.functional,
      artifact: x.options.artifact,
      connectivity: x.options.connectivity,
      diffusion: x.options.diffusion,
    });
  };
  const [saving, setSaving] = useState(false);
  const [presetNameInput, setPresetNameInput] = useState("");
  const [presetText, setPresetText] = useState("");
  const savePreset = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/presets", {
          body: {
            name: presetNameInput,
            description: presetText,
            options: { stages: opts.stages, anatomical: opts.anatomical, functional: opts.functional, artifact: opts.artifact, connectivity: opts.connectivity, diffusion: opts.diffusion },
          },
        }),
      ),
    onSuccess: (saved) => {
      void client.invalidateQueries({ queryKey: ["presets"] });
      setSaving(false);
      setPresetId(saved.id);
    },
  });
  const removePreset = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/presets/{preset_id}", { params: { path: { preset_id: id } } })),
    onSuccess: () => {
      setPresetId("custom");
      void client.invalidateQueries({ queryKey: ["presets"] });
    },
  });
  const request: FullOptions = { ...opts, subject, preset: presetName };
  const batch = subjects && subjects.length > 0 ? subjects : null;
  const batchRequest = { subjects: batch ?? [], stages: opts.stages, anatomical: opts.anatomical, functional: opts.functional, artifact: opts.artifact, connectivity: opts.connectivity, diffusion: opts.diffusion, preset: presetName };
  const plan = useQuery({
    queryKey: ["ws", ws, "plan", batch ? JSON.stringify(batchRequest) : JSON.stringify(request)],
    enabled: open,
    placeholderData: keepPreviousData, // keep the list on screen (and its scroll position) while a changed choice is re-planned
    queryFn: async () => {
      if (batch) {
        const b = await call(api.POST("/api/workspaces/{ws_id}/process/plan-batch", { params: { path: { ws_id: ws } }, body: batchRequest }));
        return { stages: b.stages, can_start: b.runnable > 0, steps: 0, batch: b };
      }
      const one = await call(api.POST("/api/workspaces/{ws_id}/process/plan", { params: { path: { ws_id: ws } }, body: request }));
      return { ...one, batch: null };
    },
  });
  const start = useMutation({
    mutationFn: () =>
      batch
        ? call(api.POST("/api/workspaces/{ws_id}/process-batch", { params: { path: { ws_id: ws } }, body: batchRequest }))
        : call(api.POST("/api/workspaces/{ws_id}/process", { params: { path: { ws_id: ws } }, body: request })),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["ws", ws] });
      onOpenChange(false);
      onStarted?.();
    },
  });
  const settingsFor = (id: string) => <StageSettings stageId={id} opts={opts} setOpts={setOpts} />;
  const p = plan.data;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="640px">
        <Dialog.Title>
          {batch ? `Process ${batch.length} subjects` : onlyStage ? `Run one stage for ${subject}` : `Process ${subject}`}
        </Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          MRForge will run these stages one after another{batch ? " for every subject, a few subjects at a time" : ""}. Work
          that is already finished and unchanged is not repeated. You can close the page while it runs.
        </Dialog.Description>
        <Flex direction="column" gap={space.group} mt="4" style={{ maxHeight: "60vh", overflowY: "auto", paddingRight: 4 }}>
          <Flex gap="2" align="end" wrap="wrap">
            <Flex direction="column" gap="1" style={{ minWidth: 260 }}>
              <Text size={type.help} weight="medium">
                Settings
              </Text>
              <Select.Root value={presetName ? presetId : "custom"} onValueChange={applyPreset}>
                <Select.Trigger aria-label="Preset" />
                <Select.Content>
                  <Select.Item value="custom">Custom (my own choices)</Select.Item>
                  {(presets.data ?? []).map((x: Preset) => (
                    <Select.Item key={x.id} value={x.id}>
                      {x.name}
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
            </Flex>
            <Button size="1" variant="soft" color="gray" onClick={() => setSaving(true)}>
              Save these settings as a preset…
            </Button>
            {chosenPreset && !chosenPreset.builtin && (
              <Button size="1" variant="ghost" color="red" onClick={() => removePreset.mutate(chosenPreset.id)}>
                Delete this preset
              </Button>
            )}
          </Flex>
          {chosenPreset && presetName && (
            <Text size={type.caption} color="gray">
              {chosenPreset.description}
            </Text>
          )}
          {plan.error && <ErrorCallout error={(plan.error as ApiError).body} />}
          {p?.stages.map((st) => (
            <StageCard
              key={st.id}
              stage={st}
              onToggle={(enabled) => setOpts({ ...opts, stages: { ...opts.stages, [st.id]: enabled } })}
              settings={STAGE_HAS_SETTINGS.has(st.id) ? settingsFor(st.id) : undefined}
              open={openCards.has(st.id)}
              onOpen={(on) =>
                setOpenCards((prev) => {
                  const next = new Set(prev);
                  if (on) next.add(st.id);
                  else next.delete(st.id);
                  return next;
                })
              }
            />
          ))}

          {p?.batch && (
            <Flex direction="column" gap="1">
              <Text size={type.help} weight="medium">
                Subjects ({p.batch.runnable} of {p.batch.subjects.length} can run)
              </Text>
              <div style={{ maxHeight: 150, overflow: "auto", border: "1px solid var(--gray-a5)", borderRadius: "var(--radius-2)", padding: "var(--space-2)" }}>
                {p.batch.subjects.map((s) => (
                  <Flex key={s.subject} justify="between" gap={space.group}>
                    <Text size={type.help}>{s.subject}</Text>
                    <Text size={type.caption} color={s.can_start ? "gray" : "orange"}>
                      {s.can_start ? `${s.steps} steps planned` : `cannot run: ${s.reason}`}
                    </Text>
                  </Flex>
                ))}
              </div>
            </Flex>
          )}

          {p && !p.can_start && (
            <Callout.Root color="amber">
              <Callout.Text>Nothing can run with these choices. Tick a stage that is possible.</Callout.Text>
            </Callout.Root>
          )}
          {start.error && <ErrorCallout error={(start.error as ApiError).body} />}
        </Flex>
        <Dialog.Root open={saving} onOpenChange={setSaving}>
          <Dialog.Content maxWidth="420px">
            <Dialog.Title>Save as a preset</Dialog.Title>
            <Dialog.Description size={type.help} color="gray">
              Everyone who uses this computer can choose it later. Saving with the same name replaces your earlier preset.
            </Dialog.Description>
            <Flex direction="column" gap="2" mt="3">
              <TextField.Root placeholder="Name, e.g. Pilot study, 6 mm" value={presetNameInput} onChange={(e) => setPresetNameInput(e.target.value)} aria-label="Preset name" autoFocus />
              <TextArea placeholder="What is it for? (optional)" value={presetText} onChange={(e) => setPresetText(e.target.value)} aria-label="Description" />
              {savePreset.error && <ErrorCallout error={(savePreset.error as ApiError).body} />}
            </Flex>
            <Flex justify="end" gap="2" mt="4">
              <Button variant="soft" color="gray" onClick={() => setSaving(false)}>
                Cancel
              </Button>
              <Button disabled={!presetNameInput.trim() || savePreset.isPending} onClick={() => savePreset.mutate()}>
                Save preset
              </Button>
            </Flex>
          </Dialog.Content>
        </Dialog.Root>
        <Flex justify="between" align="center" gap={space.group} mt="4">
          <Text size={type.help} color="gray">
            {p?.batch
              ? `${p.batch.runnable} of ${p.batch.subjects.length} subjects can run`
              : p?.can_start
                ? `${p.steps} ${p.steps === 1 ? "step" : "steps"} will run`
                : ""}
          </Text>
          <Flex gap={space.group}>
          <Dialog.Close>
            <Button variant="soft" color="gray">
              Cancel
            </Button>
          </Dialog.Close>
          <Button size="3" disabled={!p?.can_start || start.isPending} onClick={() => start.mutate()}>
            {batch ? `Start processing ${p?.batch?.runnable ?? batch.length} subjects` : "Start processing"}
          </Button>
          </Flex>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
