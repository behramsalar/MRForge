import { Checkbox, Flex, RadioGroup, Select, Switch, Text, TextField } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "../api/client";
import { call } from "../api/call";
import type { FullOptions } from "../api/types";
import { space, type } from "../theme/tokens";

/** The settings of one stage: the same controls everywhere (the Process page's side panel and
 * the confirmation dialog), so a stage's options are written once. Returns nothing for a
 * stage without settings. */
export function StageSettings({
  stageId,
  opts,
  setOpts,
}: {
  stageId: string;
  opts: FullOptions;
  setOpts: (o: FullOptions) => void;
}) {
  const health = useQuery({ queryKey: ["health"], queryFn: () => call(api.GET("/api/health")) });
  const aromaInstalled = !!health.data?.tools["ica-aroma"];
  const mrtrixInstalled = !!health.data?.tools["mrtrix3"];
  const atlases = useQuery({ queryKey: ["atlases"], queryFn: () => call(api.GET("/api/atlases")), enabled: stageId === "connectivity" });
  const f = opts.functional!;
  const setF = (change: Partial<NonNullable<FullOptions["functional"]>>) =>
    setOpts({ ...opts, functional: { ...f, ...change } });
  const a = opts.anatomical!;
  const r = opts.artifact!;
  const d = opts.diffusion!;
  const c = opts.connectivity!;
  const chosenAtlases = c.atlases ?? [];
  const toggleAtlas = (id: string, on: boolean) =>
    setOpts({
      ...opts,
      connectivity: { ...c, atlases: on ? [...chosenAtlases.filter((x) => x !== id), id] : chosenAtlases.filter((x) => x !== id) },
    });
  const setD = (change: Partial<NonNullable<FullOptions["diffusion"]>>) =>
    setOpts({ ...opts, diffusion: { ...d, ...change } });
  const functionalSettings = (
    <Flex direction="column" gap={space.group}>
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
    </Flex>
  );
  const artifactSettings = (
    <Flex direction="column" gap={space.group}>
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
    </Flex>
  );
  const diffusionSettings = (
    <Flex direction="column" gap={space.group}>
      <Text as="label" size={type.help}>
        <Flex gap={space.inline} align="center">
          <Switch checked={(d.denoise ?? true) && mrtrixInstalled} disabled={!mrtrixInstalled} onCheckedChange={(on) => setD({ denoise: on })} />
          Remove noise (MRtrix3)
        </Flex>
      </Text>
      <Text as="label" size={type.help}>
        <Flex gap={space.inline} align="center">
          <Switch checked={(d.unring ?? true) && mrtrixInstalled} disabled={!mrtrixInstalled} onCheckedChange={(on) => setD({ unring: on })} />
          Remove Gibbs ringing (MRtrix3)
        </Flex>
      </Text>
      {!mrtrixInstalled && (
        <Text size={type.caption} color="gray">
          MRtrix3 is not installed on this computer, so these two are skipped. The result says so.
        </Text>
      )}
      <Text as="label" size={type.help}>
        <Flex gap={space.inline} align="center">
          <Switch checked={d.topup ?? true} onCheckedChange={(on) => setD({ topup: on })} />
          Correct image distortion with TOPUP (where an image with the opposite phase-encoding direction exists)
        </Flex>
      </Text>
      <Text as="label" size={type.help}>
        <Flex gap={space.inline} align="center">
          <Switch checked={d.second_is_opposite ?? false} onCheckedChange={(on) => setD({ second_is_opposite: on })} />
          Philips: take the second image as the opposite direction
        </Flex>
      </Text>
      <Flex gap={space.group} wrap="wrap">
        <Flex direction="column" gap="1">
          <Text size={type.help} weight="medium">
            Eddy-current and motion correction
          </Text>
          <Select.Root value={d.eddy ?? "eddy_cpu"} onValueChange={(v) => setD({ eddy: v })}>
            <Select.Trigger aria-label="Eddy program" />
            <Select.Content>
              <Select.Item value="eddy_cpu">eddy_cpu (recommended)</Select.Item>
              <Select.Item value="eddy_correct">eddy_correct (older, simple)</Select.Item>
              <Select.Item value="eddy_cuda">eddy_cuda (needs an NVIDIA card)</Select.Item>
              <Select.Item value="none">None (flagged in the results)</Select.Item>
            </Select.Content>
          </Select.Root>
        </Flex>
        <Flex direction="column" gap="1">
          <Text size={type.help} weight="medium">
            Move the maps to
          </Text>
          <Select.Root value={d.registration ?? "linear"} onValueChange={(v) => setD({ registration: v as NonNullable<typeof d.registration> })}>
            <Select.Trigger aria-label="Registration" />
            <Select.Content>
              <Select.Item value="linear">The JHU template, linear (script default)</Select.Item>
              <Select.Item value="fnirt">The JHU template, non-linear</Select.Item>
              <Select.Item value="linear_fnirt">The JHU template, linear then non-linear</Select.Item>
              <Select.Item value="native">Nothing: measure in the person's own space</Select.Item>
            </Select.Content>
          </Select.Root>
        </Flex>
        <Flex direction="column" gap="1">
          <Text size={type.help} weight="medium">
            Through the person's
          </Text>
          <Select.Root value={d.structural ?? "none"} onValueChange={(v) => setD({ structural: v as NonNullable<typeof d.structural> })}>
            <Select.Trigger aria-label="Structural image" />
            <Select.Content>
              <Select.Item value="none">No structural image</Select.Item>
              <Select.Item value="t1">T1 image (to MNI)</Select.Item>
              <Select.Item value="t2">T2 image (to the JHU T2 template)</Select.Item>
            </Select.Content>
          </Select.Root>
        </Flex>
      </Flex>
      <Flex gap={space.group} wrap="wrap">
        <Flex direction="column" gap="1">
          <Text size={type.help} weight="medium">
            Tensor moved with
          </Text>
          <Select.Root value={d.tensor_method ?? "flirt"} onValueChange={(v) => setD({ tensor_method: v as NonNullable<typeof d.tensor_method> })}>
            <Select.Trigger aria-label="Tensor method" />
            <Select.Content>
              <Select.Item value="flirt">flirt (script default; does not rotate the tensor)</Select.Item>
              <Select.Item value="vecreg">vecreg (rotates the tensor)</Select.Item>
            </Select.Content>
          </Select.Root>
        </Flex>
        <Flex direction="column" gap="1">
          <Text size={type.help} weight="medium">
            Regions
          </Text>
          <Select.Root value={d.roi_source ?? "default"} onValueChange={(v) => setD({ roi_source: v as NonNullable<typeof d.roi_source> })}>
            <Select.Trigger aria-label="Regions" />
            <Select.Content>
              <Select.Item value="default">Packaged 2.5 mm spheres</Select.Item>
              <Select.Item value="legacy5">Packaged 5 mm boxes (older)</Select.Item>
              <Select.Item value="sphere">Spheres of my own radius</Select.Item>
            </Select.Content>
          </Select.Root>
        </Flex>
        {d.roi_source === "sphere" && (
          <Flex direction="column" gap="1">
            <Text size={type.help} weight="medium">
              Radius (mm)
            </Text>
            <TextField.Root
              type="number"
              min="0.5"
              max="20"
              step="0.5"
              value={String(d.roi_radius_mm ?? 2.5)}
              onChange={(e) => setD({ roi_radius_mm: Math.min(20, Math.max(0.5, Number(e.target.value) || 2.5)) })}
              style={{ width: 110 }}
            />
          </Flex>
        )}
      </Flex>
      <Text size={type.caption} color="gray">
        Eddy-current correction takes hours on a normal computer. Your own region files are available from the command line.
      </Text>
    </Flex>
  );
  const anatomicalSettings = (
    <Flex direction="column" gap={space.group}>
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
  );
  const connectivitySettings = (
    <Flex direction="column" gap={space.group}>
      <Text size={type.help} weight="medium">
        Atlases (each one gets its own results; choose one or more)
      </Text>
      {(atlases.data?.families ?? []).map((family) => (
        <Flex key={family.id} direction="column" gap="1">
          <Text size={type.caption} color="gray">
            {family.name}: {family.kind}
          </Text>
          {(atlases.data?.atlases ?? [])
            .filter((x) => x.family === family.id)
            .map((x) => (
              <Flex key={x.id} direction="column" gap="1">
                <Text as="label" size={type.help}>
                  <Flex gap={space.inline} align="center">
                    <Checkbox checked={chosenAtlases.includes(x.id)} onCheckedChange={(v) => toggleAtlas(x.id, v === true)} />
                    {x.name} ({x.regions} regions)
                  </Flex>
                </Text>
                {chosenAtlases.includes(x.id) && x.caveat && (
                  <Text size={type.caption} color="gray" style={{ marginLeft: 24 }}>
                    {x.caveat}
                  </Text>
                )}
              </Flex>
            ))}
        </Flex>
      ))}
      <Text as="label" size={type.help}>
        <Flex gap={space.inline} align="center">
          <Switch
            checked={c.only_voxels_with_signal ?? true}
            onCheckedChange={(on) => setOpts({ ...opts, connectivity: { ...c, only_voxels_with_signal: on } })}
          />
          Average only voxels inside the brain of each run (recommended; otherwise every voxel of a region is used)
        </Flex>
      </Text>
      <Text size={type.caption} color="gray">
        Needs the run in standard space at 2 mm. The cleaned data is used when artifact rejection was done.
      </Text>
    </Flex>
  );
  const settingsFor: Record<string, ReactNode> = {
    anatomical: anatomicalSettings,
    functional: functionalSettings,
    artifact_rejection: artifactSettings,
    connectivity: connectivitySettings,
    diffusion: diffusionSettings,
  };
  return <>{settingsFor[stageId] ?? null}</>;
}
