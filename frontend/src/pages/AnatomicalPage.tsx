import { Button, Callout, Card, Flex, Heading, Select, Switch, Text } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useSubjects } from "../api/hooks";
import type { WorkspaceState } from "../api/types";
import { ErrorCallout } from "../components/ErrorCallout";
import { JobsPanel } from "../components/JobsPanel";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

export function AnatomicalPage({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  const client = useQueryClient();
  const subjects = useSubjects(ws);
  const withT1 = (subjects.data ?? []).filter((s) => s.files.some((f) => f.kind === "T1w"));
  const [chosen, setChosen] = useState<string | undefined>();
  const subject = withT1.find((s) => s.label === chosen) ?? withT1[0];
  const t1s = subject?.files.filter((f) => f.kind === "T1w") ?? [];
  const [t1, setT1] = useState<string | undefined>();
  const t1Path = t1s.find((f) => f.relpath === t1)?.relpath ?? t1s[0]?.relpath;
  const [bet, setBet] = useState(false);
  const [strongBias, setStrongBias] = useState(false);
  const [subcortical, setSubcortical] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");

  const start = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/anat", {
          params: { path: { ws_id: ws } },
          body: {
            subject: subject!.label,
            t1: t1Path!,
            bet,
            strong_bias: strongBias,
            subcortical_segmentation: subcortical,
          },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["ws", ws] }),
  });

  const anatJobs = (state?.jobs ?? []).filter((j) => j.step === "fsl_anat" || j.step === "bet");
  return (
    <Flex direction="column" gap={space.section}>
      <Flex direction="column" gap="1">
        <Heading size={type.pageTitle}>Anatomical processing</Heading>
        <Text color="gray" size={type.body}>
          Prepares the T1 image of a subject: removes the skull, corrects intensity differences,
          separates tissue types and prepares the alignment to standard space.
        </Text>
      </Flex>

      {withT1.length === 0 && subjects.data && (
        <Callout.Root>
          <Callout.Text>
            There is no T1 image to process yet. <a href={href(ws, "import")}>Import scans first.</a>
          </Callout.Text>
        </Callout.Root>
      )}

      {subject && (
        <Card>
          <Flex direction="column" gap={space.group}>
            <Flex gap={space.group} wrap="wrap">
              <Flex direction="column" gap="1">
                <Text size={type.help} weight="medium">
                  Subject
                </Text>
                <Select.Root value={subject.label} onValueChange={setChosen}>
                  <Select.Trigger />
                  <Select.Content>
                    {withT1.map((s) => (
                      <Select.Item key={s.label} value={s.label}>
                        {s.label}
                      </Select.Item>
                    ))}
                  </Select.Content>
                </Select.Root>
              </Flex>
              {t1s.length > 1 && (
                <Flex direction="column" gap="1">
                  <Text size={type.help} weight="medium">
                    T1 image
                  </Text>
                  <Select.Root value={t1Path} onValueChange={setT1}>
                    <Select.Trigger />
                    <Select.Content>
                      {t1s.map((f) => (
                        <Select.Item key={f.relpath} value={f.relpath}>
                          {f.relpath.split("/").pop()}
                        </Select.Item>
                      ))}
                    </Select.Content>
                  </Select.Root>
                </Flex>
              )}
            </Flex>

            <Button variant="ghost" size="1" style={{ alignSelf: "flex-start" }} onClick={() => setShowMore(!showMore)}>
              {showMore ? "Hide advanced options" : "Advanced options"}
            </Button>
            {showMore && (
              <Flex direction="column" gap={space.group}>
                <Text as="label" size={type.help}>
                  <Flex gap={space.inline} align="center">
                    <Switch checked={bet} onCheckedChange={setBet} />
                    Also save a separate brain-only image (bet). Not needed for the processing itself.
                  </Flex>
                </Text>
                <Text as="label" size={type.help}>
                  <Flex gap={space.inline} align="center">
                    <Switch checked={strongBias} onCheckedChange={setStrongBias} />
                    Strong intensity correction (for images with very uneven brightness)
                  </Flex>
                </Text>
                <Text as="label" size={type.help}>
                  <Flex gap={space.inline} align="center">
                    <Switch checked={subcortical} onCheckedChange={setSubcortical} />
                    Also segment deep brain structures (slow; not needed for the functional pipeline)
                  </Flex>
                </Text>
              </Flex>
            )}

            <Flex gap={space.group} align="center" wrap="wrap">
              <Button size="3" disabled={busy || start.isPending || !t1Path} onClick={() => start.mutate()}>
                Start processing {subject.label}
              </Button>
              <Text size={type.help} color="gray">
                This can take a long time. You can close the page; the work continues and finished steps are kept.
              </Text>
            </Flex>
            {start.error && <ErrorCallout error={(start.error as ApiError).body} />}
          </Flex>
        </Card>
      )}

      <JobsPanel
        ws={ws}
        jobs={anatJobs}
        busy={busy}
        action={(j) =>
          j.step === "fsl_anat" && j.subject ? (
            <Button asChild size="1">
              <a href={href(ws, "view", j.subject)}>View result</a>
            </Button>
          ) : null
        }
      />
    </Flex>
  );
}
