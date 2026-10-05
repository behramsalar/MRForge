import { Badge, Button, Callout, Checkbox, Dialog, Flex, Switch, Text, TextField } from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { FullOptions, StagePlan } from "../api/types";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

const DEFAULTS: FullOptions = {
  subject: "",
  stages: {},
  anatomical: { strong_bias: false, subcortical_segmentation: false },
  functional: {
    delete_volumes: 5,
    smoothing_fwhm_mm: 5,
    highpass_cutoff_s: 150,
    use_fieldmap: true,
    slice_timing: false,
  },
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
export function ConfirmProcessDialog({
  ws,
  subject,
  open,
  onOpenChange,
  onStarted,
}: {
  ws: string;
  subject: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted?: () => void;
}) {
  const client = useQueryClient();
  const [opts, setOpts] = useState<FullOptions>({ ...DEFAULTS, subject });
  const [showMore, setShowMore] = useState(false);
  const request: FullOptions = { ...opts, subject };
  const plan = useQuery({
    queryKey: ["ws", ws, "plan", JSON.stringify(request)],
    enabled: open,
    queryFn: () => call(api.POST("/api/workspaces/{ws_id}/process/plan", { params: { path: { ws_id: ws } }, body: request })),
  });
  const start = useMutation({
    mutationFn: () => call(api.POST("/api/workspaces/{ws_id}/process", { params: { path: { ws_id: ws } }, body: request })),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["ws", ws] });
      onOpenChange(false);
      onStarted?.();
    },
  });
  const f = opts.functional!;
  const setF = (change: Partial<NonNullable<FullOptions["functional"]>>) =>
    setOpts({ ...opts, functional: { ...f, ...change } });
  const a = opts.anatomical!;
  const p = plan.data;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="640px">
        <Dialog.Title>Process {subject}</Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          MRForge will run these stages one after another. Work that is already finished and unchanged is not
          repeated. You can close the page while it runs.
        </Dialog.Description>
        <Flex direction="column" gap={space.group} mt="4">
          {plan.error && <ErrorCallout error={(plan.error as ApiError).body} />}
          {p?.stages.map((st) => (
            <StageBlock
              key={st.id}
              stage={st}
              onToggle={(enabled) => setOpts({ ...opts, stages: { ...opts.stages, [st.id]: enabled } })}
            />
          ))}

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
            </Flex>
          )}
          {p && !p.can_start && (
            <Callout.Root color="amber">
              <Callout.Text>Nothing can run with these choices. Tick a stage that is possible.</Callout.Text>
            </Callout.Root>
          )}
          {start.error && <ErrorCallout error={(start.error as ApiError).body} />}
        </Flex>
        <Flex justify="end" gap={space.group} mt="4">
          <Dialog.Close>
            <Button variant="soft" color="gray">
              Cancel
            </Button>
          </Dialog.Close>
          <Button size="3" disabled={!p?.can_start || start.isPending} onClick={() => start.mutate()}>
            Start processing
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
