import { Badge, Button, Callout, Checkbox, Dialog, Flex, RadioGroup, Select, Switch, Text, TextArea, TextField } from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { FullOptions, Preset, StagePlan } from "../api/types";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

const STAGE_IDS = ["anatomical", "functional", "artifact_rejection", "standard_space"];

const DEFAULTS: FullOptions = {
  subject: "",
  stages: {},
  anatomical: { strong_bias: false, subcortical_segmentation: false, resample_to_1mm: false },
  functional: {
    delete_volumes: 5,
    smoothing_fwhm_mm: 5,
    highpass_cutoff_s: 150,
    use_fieldmap: true,
    slice_timing: false,
  },
  artifact: { uncertain_as: "signal", aggressive: false, mode: "manual" },
};

function StageBlock({
  stage,
  onToggle,
}: {
  stage: StagePlan;
  onToggle: (enabled: boolean) => void;
}) {
  return (
    <Flex direction="column" gap="2" style={{ opacity: stage.can_run ? 1 : 0.7 }}>
      <Text as="label" size={type.body}>
        <Flex gap={space.inline} align="center">
          <Checkbox checked={stage.enabled && stage.can_run} disabled={!stage.can_run} onCheckedChange={(v) => onToggle(v === true)} />
          <Text weight="bold">{stage.label}</Text>
          {stage.already_done && (
            <Badge color="green" variant="soft">
              Done earlier: not repeated if unchanged
            </Badge>
          )}
        </Flex>
      </Text>
      <Text size={type.help} color="gray" style={{ paddingLeft: 28 }}>
        {stage.can_run ? stage.description : `Not possible: ${stage.reason}`}
      </Text>
      {stage.enabled && stage.can_run && (
        <Flex direction="column" gap="2" style={{ paddingLeft: 28 }}>
          {stage.items.map((item) => (
            <Flex key={item.title} direction="column" gap="1">
              <Text size={type.help} weight="medium">
                {item.title}
              </Text>
              {item.note && (
                <Text size={type.caption} color="orange">
                  {item.note}
                </Text>
              )}
              <Text size={type.caption} color="gray">
                {item.settings.map((s) => `${s.name}: ${s.value}`).join(" · ")}
              </Text>
            </Flex>
          ))}
        </Flex>
      )}
    </Flex>
  );
}

/** The confirmation before full processing: what will run, with the default settings, anything
 * left out and why, and a way to change the settings. Stages come from the plan, so a new
 * stage shows up here without changes to this dialog. */
/** The choices without the subject, in a stable form, to see whether they still equal a preset. */
function signature(o: Pick<FullOptions, "stages" | "anatomical" | "functional" | "artifact">): string {
  const sort = (v: unknown): unknown =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([k, x]) => [k, sort(x)]))
      : v;
  return JSON.stringify(sort({ s: o.stages ?? {}, a: o.anatomical, f: o.functional, r: o.artifact }));
}

export function ConfirmProcessDialog({
  ws,
  subject,
  open,
  onOpenChange,
  onStarted,
  onlyStage,
  subjects,
}: {
  ws: string;
  subject: string;
  onlyStage?: string; // run just this stage (the others are unticked; earlier results are used)
  subjects?: string[]; // several subjects at once (a batch): the same choices for all of them
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted?: () => void;
}) {
  const client = useQueryClient();
  const [opts, setOpts] = useState<FullOptions>({
    ...DEFAULTS,
    subject,
    stages: onlyStage ? Object.fromEntries(STAGE_IDS.map((id) => [id, id === onlyStage])) : {},
  });
  const [showMore, setShowMore] = useState(false);
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
      stages: onlyStage ? opts.stages : x.options.stages,
      anatomical: x.options.anatomical,
      functional: x.options.functional,
      artifact: x.options.artifact,
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
            options: { stages: opts.stages, anatomical: opts.anatomical, functional: opts.functional, artifact: opts.artifact },
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
  const batchRequest = { subjects: batch ?? [], stages: opts.stages, anatomical: opts.anatomical, functional: opts.functional, artifact: opts.artifact, preset: presetName };
  const plan = useQuery({
    queryKey: ["ws", ws, "plan", batch ? JSON.stringify(batchRequest) : JSON.stringify(request)],
    enabled: open,
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
  const health = useQuery({ queryKey: ["health"], queryFn: () => call(api.GET("/api/health")) });
  const aromaInstalled = !!health.data?.tools["ica-aroma"];
  const f = opts.functional!;
  const setF = (change: Partial<NonNullable<FullOptions["functional"]>>) =>
    setOpts({ ...opts, functional: { ...f, ...change } });
  const a = opts.anatomical!;
  const r = opts.artifact!;
  const artifactOn = opts.stages?.artifact_rejection === true;
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
        <Flex direction="column" gap={space.group} mt="4">
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
            <StageBlock
              key={st.id}
              stage={st}
              onToggle={(enabled) => setOpts({ ...opts, stages: { ...opts.stages, [st.id]: enabled } })}
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

          <Button variant="ghost" size="1" style={{ alignSelf: "flex-start" }} onClick={() => setShowMore(!showMore)}>
            {showMore ? "Hide settings" : "Change settings"}
          </Button>
          {showMore && (
            <Flex direction="column" gap={space.group} style={{ paddingLeft: 4 }}>
              <Flex gap={space.group} wrap="wrap">
                <Flex direction="column" gap="1">
                  <Text size={type.help} weight="medium">
                    Volumes to discard
                  </Text>
                  <TextField.Root
                    type="number"
                    min="0"
                    value={String(f.delete_volumes ?? 5)}
                    onChange={(e) => setF({ delete_volumes: Math.max(0, Math.round(Number(e.target.value) || 0)) })}
                    style={{ width: 110 }}
                  />
                </Flex>
                <Flex direction="column" gap="1">
                  <Text size={type.help} weight="medium">
                    Smoothing (mm)
                  </Text>
                  <TextField.Root
                    type="number"
                    min="0"
                    max="20"
                    value={String(f.smoothing_fwhm_mm ?? 5)}
                    onChange={(e) => setF({ smoothing_fwhm_mm: Math.min(20, Math.max(0, Number(e.target.value) || 0)) })}
                    style={{ width: 110 }}
                  />
                </Flex>
                <Flex direction="column" gap="1">
                  <Text size={type.help} weight="medium">
                    Drift filter (seconds)
                  </Text>
                  <TextField.Root
                    type="number"
                    min="1"
                    disabled={f.highpass_cutoff_s == null}
                    value={String(f.highpass_cutoff_s ?? 150)}
                    onChange={(e) => setF({ highpass_cutoff_s: Math.max(1, Number(e.target.value) || 150) })}
                    style={{ width: 110 }}
                  />
                </Flex>
              </Flex>
              <Text as="label" size={type.help}>
                <Flex gap={space.inline} align="center">
                  <Switch
                    checked={f.highpass_cutoff_s != null}
                    onCheckedChange={(on) => setF({ highpass_cutoff_s: on ? 150 : null })}
                  />
                  Remove slow signal drifts
                </Flex>
              </Text>
              <Text as="label" size={type.help}>
                <Flex gap={space.inline} align="center">
                  <Switch checked={f.use_fieldmap ?? true} onCheckedChange={(on) => setF({ use_fieldmap: on })} />
                  Correct image distortion with the fieldmap (where one exists)
                </Flex>
              </Text>
              <Text as="label" size={type.help}>
                <Flex gap={space.inline} align="center">
                  <Switch checked={f.slice_timing ?? false} onCheckedChange={(on) => setF({ slice_timing: on })} />
                  Slice timing correction (where the scan records it)
                </Flex>
              </Text>
              {artifactOn && (
                <>
                  <Flex direction="column" gap="1">
                    <Text size={type.help} weight="medium">
                      Who labels the components?
                    </Text>
                    <RadioGroup.Root
                      value={r.mode ?? "manual"}
                      onValueChange={(v) => setOpts({ ...opts, artifact: { ...r, mode: v as NonNullable<typeof r.mode> } })}
                    >
                      <RadioGroup.Item value="manual">You (the processing pauses until you have labelled them)</RadioGroup.Item>
                      <RadioGroup.Item value="aroma_review" disabled={!aromaInstalled}>
                        ICA-AROMA proposes, you confirm (the processing pauses)
                      </RadioGroup.Item>
                      <RadioGroup.Item value="aroma_auto" disabled={!aromaInstalled}>
                        ICA-AROMA decides (no pause; you can look at the result afterwards)
                      </RadioGroup.Item>
                    </RadioGroup.Root>
                    {!aromaInstalled && (
                      <Text size={type.caption} color="gray">
                        ICA-AROMA is not installed on this computer, so only labelling by you is available.
                      </Text>
                    )}
                  </Flex>
                  <Text as="label" size={type.help}>
                    <Flex gap={space.inline} align="center">
                      <Switch
                        checked={r.uncertain_as === "noise"}
                        onCheckedChange={(on) => setOpts({ ...opts, artifact: { ...r, uncertain_as: on ? "noise" : "signal" } })}
                      />
                      Also remove components I mark "uncertain" (otherwise they are kept)
                    </Flex>
                  </Text>
                  <Text as="label" size={type.help}>
                    <Flex gap={space.inline} align="center">
                      <Switch
                        checked={r.aggressive ?? false}
                        onCheckedChange={(on) => setOpts({ ...opts, artifact: { ...r, aggressive: on } })}
                      />
                      Aggressive removal (removes more; also signal shared with good components)
                    </Flex>
                  </Text>
                </>
              )}
              <Text as="label" size={type.help}>
                <Flex gap={space.inline} align="center">
                  <Switch
                    checked={a.subcortical_segmentation ?? false}
                    onCheckedChange={(on) => setOpts({ ...opts, anatomical: { ...a, subcortical_segmentation: on } })}
                  />
                  Also segment deep brain structures (slow)
                </Flex>
              </Text>
              <Text as="label" size={type.help}>
                <Flex gap={space.inline} align="center">
                  <Switch
                    checked={a.strong_bias ?? false}
                    onCheckedChange={(on) => setOpts({ ...opts, anatomical: { ...a, strong_bias: on } })}
                  />
                  Strong intensity correction of the T1
                </Flex>
              </Text>
              <Text as="label" size={type.help}>
                <Flex gap={space.inline} align="center">
                  <Switch
                    checked={a.resample_to_1mm ?? false}
                    onCheckedChange={(on) => setOpts({ ...opts, anatomical: { ...a, resample_to_1mm: on } })}
                  />
                  Resample the T1 to 1 mm voxels first (much faster for very high-resolution scans)
                </Flex>
              </Text>
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
        <Flex justify="end" gap={space.group} mt="4">
          <Dialog.Close>
            <Button variant="soft" color="gray">
              Cancel
            </Button>
          </Dialog.Close>
          <Button size="3" disabled={!p?.can_start || start.isPending} onClick={() => start.mutate()}>
            {batch ? `Start processing ${p?.batch?.runnable ?? batch.length} subjects` : "Start processing"}
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
