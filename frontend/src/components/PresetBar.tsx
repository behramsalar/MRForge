import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Dialog, Flex, Select, Text, TextArea, TextField } from "@radix-ui/themes";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { FullOptions, Preset } from "../api/types";
import { DEFAULTS, signature } from "../lib/processOptions";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

const OPTION_KEYS = ["stages", "anatomical", "functional", "artifact", "connectivity", "diffusion"] as const;
const pick = (o: FullOptions) => ({ stages: o.stages, anatomical: o.anatomical, functional: o.functional, artifact: o.artifact, connectivity: o.connectivity, diffusion: o.diffusion });

/** Choose, save, update and delete presets (a preset is the stage switches plus every setting).
 * Saving with an existing name replaces that preset, which is how "Update" works. Built-in
 * presets can be chosen but not changed. */
export function PresetBar({
  opts,
  onChange,
  presetId,
  onPresetId,
}: {
  opts: FullOptions;
  onChange: (o: FullOptions) => void;
  presetId: string;
  onPresetId: (id: string) => void;
}) {
  const client = useQueryClient();
  const presets = useQuery({ queryKey: ["presets"], queryFn: () => call(api.GET("/api/presets")) });
  const chosen = (presets.data ?? []).find((x) => x.id === presetId);
  const matches = (p: Preset) => signature(p.options as never) === signature(opts);
  const modified = chosen ? !matches(chosen) : signature(pick(DEFAULTS) as never) !== signature(pick(opts) as never);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const save = useMutation({
    mutationFn: (n: { name: string; description: string }) =>
      call(api.POST("/api/presets", { body: { name: n.name, description: n.description, options: pick(opts) } })),
    onSuccess: (saved) => {
      void client.invalidateQueries({ queryKey: ["presets"] });
      setSaving(false);
      onPresetId(saved.id);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/presets/{preset_id}", { params: { path: { preset_id: id } } })),
    onSuccess: () => {
      onPresetId("custom");
      void client.invalidateQueries({ queryKey: ["presets"] });
    },
  });
  const apply = (id: string) => {
    onPresetId(id);
    const x = presets.data?.find((q) => q.id === id);
    if (!x) {
      onChange({ ...DEFAULTS, subject: opts.subject });
      return;
    }
    const o = x.options;
    onChange({ ...opts, ...Object.fromEntries(OPTION_KEYS.map((k) => [k, o[k]])) } as FullOptions);
  };
  return (
    <Flex gap={space.group} align="center" wrap="wrap">
      <Text size={type.help} weight="medium">
        Preset
      </Text>
      <Select.Root value={chosen ? presetId : "custom"} onValueChange={apply}>
        <Select.Trigger aria-label="Preset" style={{ minWidth: 220 }} />
        <Select.Content>
          <Select.Item value="custom">Default settings</Select.Item>
          {(presets.data ?? []).map((x) => (
            <Select.Item key={x.id} value={x.id}>
              {x.name}
            </Select.Item>
          ))}
        </Select.Content>
      </Select.Root>
      {modified && (
        <Text size={type.help} color="amber">
          Changed
        </Text>
      )}
      {modified && chosen && !chosen.builtin && (
        <Button size="1" variant="soft" disabled={save.isPending} onClick={() => save.mutate({ name: chosen.name, description: chosen.description })}>
          Update “{chosen.name}”
        </Button>
      )}
      {modified && (
        <Button
          size="1"
          variant="soft"
          color="gray"
          onClick={() => {
            setName("");
            setText("");
            setSaving(true);
          }}
        >
          Save as a new preset…
        </Button>
      )}
      {modified && (
        <Button size="1" variant="ghost" color="gray" onClick={() => apply(chosen ? presetId : "custom")}>
          Undo changes
        </Button>
      )}
      {chosen && !chosen.builtin && !modified && (
        <Button size="1" variant="ghost" color="red" onClick={() => remove.mutate(chosen.id)}>
          Delete this preset
        </Button>
      )}
      {chosen?.description && !modified && (
        <Text size={type.caption} color="gray">
          {chosen.description}
        </Text>
      )}
      {save.error && !saving && <ErrorCallout error={(save.error as ApiError).body} />}
      <Dialog.Root open={saving} onOpenChange={setSaving}>
        <Dialog.Content maxWidth="420px">
          <Dialog.Title>Save as a preset</Dialog.Title>
          <Dialog.Description size={type.help} color="gray">
            Everyone who uses this computer can choose it later. Saving with the same name replaces your earlier preset.
          </Dialog.Description>
          <Flex direction="column" gap="2" mt="3">
            <TextField.Root placeholder="Name, e.g. Pilot study, 6 mm" value={name} onChange={(e) => setName(e.target.value)} aria-label="Preset name" autoFocus />
            <TextArea placeholder="What is it for? (optional)" value={text} onChange={(e) => setText(e.target.value)} aria-label="Description" />
            {save.error && <ErrorCallout error={(save.error as ApiError).body} />}
          </Flex>
          <Flex justify="end" gap="2" mt="4">
            <Button variant="soft" color="gray" onClick={() => setSaving(false)}>
              Cancel
            </Button>
            <Button disabled={!name.trim() || save.isPending} onClick={() => save.mutate({ name, description: text })}>
              Save preset
            </Button>
          </Flex>
        </Dialog.Content>
      </Dialog.Root>
    </Flex>
  );
}
