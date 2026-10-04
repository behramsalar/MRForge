import { Button, Callout, Card, Flex, Heading, Select, Switch, Text, TextField } from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useSubjects } from "../api/hooks";
import type { WorkspaceState } from "../api/types";
import { ErrorCallout } from "../components/ErrorCallout";
import { JobsPanel } from "../components/JobsPanel";
import { QcPanel } from "../components/QcPanel";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

const FUNC_STEPS = ["fieldmap_prep", "feat_preproc", "func_qc", "func_to_mni"];

export function FunctionalPage({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  const client = useQueryClient();
  const subjects = useSubjects(ws);
  const withBold = (subjects.data ?? []).filter((s) => s.files.some((f) => f.kind === "bold"));
  const [chosen, setChosen] = useState<string | undefined>();
  const subject = withBold.find((s) => s.label === chosen)?.label ?? withBold[0]?.label;

  const ready = useQuery({
    queryKey: ["ws", ws, "functional", subject],
    enabled: !!subject,
    queryFn: () =>
      call(
        api.GET("/api/workspaces/{ws_id}/subjects/{label}/functional", {
          params: { path: { ws_id: ws, label: subject! } },
        }),
      ),
  });
  const runs = ready.data?.runs ?? [];
  const [runPath, setRunPath] = useState<string | undefined>();
  const run = runs.find((r) => r.bold === runPath) ?? runs[0];

  const [discard, setDiscard] = useState("5");
  const [smooth, setSmooth] = useState("5");
  const [drift, setDrift] = useState(true);
  const [cutoff, setCutoff] = useState("150");
  const [fieldmap, setFieldmap] = useState(true);
  const [toMni, setToMni] = useState(true);
  const [showMore, setShowMore] = useState(false);
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");

  const useFieldmap = !!run?.fieldmap.available && fieldmap;
  const numbers = {
    discard: Number(discard),
    smooth: Number(smooth),
    cutoff: Number(cutoff),
  };
  const valid =
    Number.isInteger(numbers.discard) &&
    numbers.discard >= 0 &&
    numbers.smooth >= 0 &&
    numbers.smooth <= 20 &&
    (!drift || numbers.cutoff > 0);

  const start = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/functional", {
          params: { path: { ws_id: ws } },
          body: {
            subject: subject!,
            bold: run!.bold,
            delete_volumes: numbers.discard,
            smoothing_fwhm_mm: numbers.smooth,
            highpass_cutoff_s: drift ? numbers.cutoff : null,
            use_fieldmap: useFieldmap,
            to_mni: toMni,
          },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["ws", ws] }),
  });

  const funcJobs = (state?.jobs ?? []).filter((j) => FUNC_STEPS.includes(j.step));
  return (
    <Flex direction="column" gap={space.section}>
      <Flex direction="column" gap="1">
        <Heading size={type.pageTitle}>Functional preprocessing</Heading>
        <Text color="gray" size={type.body}>
          Prepares a functional (BOLD) run for analysis: corrects head motion and image distortion,
          smooths the data, aligns it to the T1 and moves it into standard space.
        </Text>
      </Flex>

      {withBold.length === 0 && subjects.data && (
        <Callout.Root>
          <Callout.Text>
            There is no functional scan to process yet. <a href={href(ws, "import")}>Import scans first.</a>
          </Callout.Text>
        </Callout.Root>
      )}

      {subject && ready.data && !ready.data.anat_ready && (
        <Callout.Root color="amber">
          <Callout.Text>
            {ready.data.anat_reason}{" "}
            <a href={href(ws, "anat")}>Go to anatomical processing.</a>
          </Callout.Text>
        </Callout.Root>
      )}
      {ready.error && <ErrorCallout error={(ready.error as ApiError).body} />}

      {subject && run && (
        <Card>
          <Flex direction="column" gap={space.group}>
            <Flex gap={space.group} wrap="wrap">
              <Flex direction="column" gap="1">
                <Text size={type.help} weight="medium">
                  Subject
                </Text>
                <Select.Root value={subject} onValueChange={setChosen}>
                  <Select.Trigger />
                  <Select.Content>
                    {withBold.map((s) => (
                      <Select.Item key={s.label} value={s.label}>
                        {s.label}
                      </Select.Item>
                    ))}
                  </Select.Content>
                </Select.Root>
              </Flex>
              {runs.length > 1 && (
                <Flex direction="column" gap="1">
                  <Text size={type.help} weight="medium">
                    Functional run
                  </Text>
                  <Select.Root value={run.bold} onValueChange={setRunPath}>
                    <Select.Trigger />
                    <Select.Content>
                      {runs.map((r) => (
                        <Select.Item key={r.bold} value={r.bold}>
                          {r.name} {r.volumes ? `(${r.volumes} volumes)` : ""}
                        </Select.Item>
                      ))}
                    </Select.Content>
                  </Select.Root>
                </Flex>
              )}
            </Flex>

            <Flex direction="column" gap="1">
              <Text as="label" size={type.body}>
                <Flex gap={space.inline} align="center">
                  <Switch checked={useFieldmap} disabled={!run.fieldmap.available} onCheckedChange={setFieldmap} />
                  Correct image distortion with the fieldmap
                </Flex>
              </Text>
              {!run.fieldmap.available && (
                <Text size={type.help} color="gray">
                  Not possible for this run: {run.fieldmap.reason}
                </Text>
              )}
            </Flex>
            <Text as="label" size={type.body}>
              <Flex gap={space.inline} align="center">
                <Switch checked={toMni} onCheckedChange={setToMni} />
                Also place the result in standard (MNI) space
              </Flex>
            </Text>

            <Text size={type.help} color="gray">
              Standard settings: discard the first {discard} volumes, smooth by {smooth} mm
              {drift ? `, remove slow drifts slower than ${cutoff} s` : ", no drift filter"}.
            </Text>
            <Button variant="ghost" size="1" style={{ alignSelf: "flex-start" }} onClick={() => setShowMore(!showMore)}>
              {showMore ? "Hide advanced options" : "Advanced options"}
            </Button>
            {showMore && (
              <Flex direction="column" gap={space.group}>
                <Flex gap={space.group} wrap="wrap">
                  <Flex direction="column" gap="1">
                    <Text size={type.help} weight="medium">
                      Volumes to discard at the start
                    </Text>
                    <TextField.Root type="number" min="0" value={discard} onChange={(e) => setDiscard(e.target.value)} style={{ width: 120 }} />
                    <Text size={type.caption} color="gray">
                      The first scans are taken while the signal settles.
                    </Text>
                  </Flex>
                  <Flex direction="column" gap="1">
                    <Text size={type.help} weight="medium">
                      Smoothing (FWHM, mm)
                    </Text>
                    <TextField.Root type="number" min="0" max="20" value={smooth} onChange={(e) => setSmooth(e.target.value)} style={{ width: 120 }} />
                    <Text size={type.caption} color="gray">
                      0 turns smoothing off.
                    </Text>
                  </Flex>
                </Flex>
                <Flex direction="column" gap="1">
                  <Text as="label" size={type.help}>
                    <Flex gap={space.inline} align="center">
                      <Switch checked={drift} onCheckedChange={setDrift} />
                      Remove slow signal drifts (high-pass filter)
                    </Flex>
                  </Text>
                  {drift && (
                    <Flex direction="column" gap="1">
                      <Text size={type.help} weight="medium">
                        Cut-off (seconds)
                      </Text>
                      <TextField.Root type="number" min="1" value={cutoff} onChange={(e) => setCutoff(e.target.value)} style={{ width: 120 }} />
                    </Flex>
                  )}
                </Flex>
              </Flex>
            )}

            <Flex gap={space.group} align="center" wrap="wrap">
              <Button
                size="3"
                disabled={busy || start.isPending || !valid || !ready.data?.anat_ready}
                onClick={() => start.mutate()}
              >
                Start preprocessing
              </Button>
              <Text size={type.help} color="gray">
                This can take a long time for a full run. You can close the page; the work continues and
                finished steps are kept.
              </Text>
            </Flex>
            {start.error && <ErrorCallout error={(start.error as ApiError).body} />}
          </Flex>
        </Card>
      )}

      <JobsPanel
        ws={ws}
        jobs={funcJobs}
        busy={busy}
        action={(j) =>
          j.step === "func_qc" && j.subject ? (
            <Button asChild size="1" variant="soft">
              <a href={href(ws, "view", j.subject)}>Open in viewer</a>
            </Button>
          ) : null
        }
      />
      {subject && <QcPanel ws={ws} subject={subject} />}
    </Flex>
  );
}
