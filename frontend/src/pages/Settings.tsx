import { Badge, Card, Flex, Heading, SegmentedControl, Table, Text, TextField } from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { MotionThresholds, ResourcePolicy } from "../api/types";
import { ErrorCallout } from "../components/ErrorCallout";
import { PageHeader } from "../components/ui/Layout";
import { useAppTheme, type Mode } from "../shell/ThemeProvider";
import { space, type } from "../theme/tokens";

const toolName: Record<string, string> = {
  fsl: "FSL",
  dcm2niix: "dcm2niix (DICOM conversion)",
  "bids-validator": "BIDS validator",
  "ica-aroma": "ICA-AROMA (optional: automatic component labelling)",
};

const PRESET_TEXT: Record<string, string> = {
  balanced: "Balanced: about half of the computer, so you can keep working.",
  max: "Max performance: all cores. The computer will feel slow meanwhile.",
  low: "Low impact: one job at a time, little memory. Slow, but unnoticeable.",
  custom: "Your own numbers.",
};

/** How much of the computer processing may use. A job waits when a limit is reached. */
function ResourcesCard() {
  const client = useQueryClient();
  const info = useQuery({ queryKey: ["resources"], queryFn: () => call(api.GET("/api/resources")), refetchInterval: 10000 });
  const save = useMutation({
    mutationFn: (policy: ResourcePolicy) => call(api.PUT("/api/resources", { body: policy })),
    onSuccess: () => client.invalidateQueries({ queryKey: ["resources"] }),
  });
  const d = info.data;
  if (!d) return null;
  const p = d.policy;
  const set = (change: Partial<ResourcePolicy>) => save.mutate({ ...p, preset: "custom", ...change });
  const field = (label: string, key: "max_subjects" | "threads_per_job" | "cpu_cap" | "memory_reserve_gb", hint: string, step = 1) => (
    <Flex direction="column" gap="1" style={{ width: 170 }}>
      <Text size={type.help} weight="medium">
        {label}
      </Text>
      <TextField.Root
        type="number"
        min={key === "memory_reserve_gb" ? 0 : 1}
        step={step}
        value={String(p[key])}
        onChange={(e) => {
          const v = Number(e.target.value);
          if (Number.isFinite(v) && v >= 0) set({ [key]: key === "memory_reserve_gb" ? v : Math.max(1, Math.round(v)) });
        }}
      />
      <Text size={type.caption} color="gray">
        {hint}
      </Text>
    </Flex>
  );
  return (
    <Card size="3">
      <Flex direction="column" gap={space.group}>
        <Heading as="h2" size={type.sectionTitle}>
          Computer resources
        </Heading>
        <Text size={type.help} color="gray">
          This computer has {d.machine.cores} cores and {d.machine.ram_gb} GB of memory ({d.machine.free_ram_gb} GB free now;{" "}
          {d.machine.jobs_running} processing job{d.machine.jobs_running === 1 ? "" : "s"} running). When a limit is reached, the next
          step simply waits.
        </Text>
        <SegmentedControl.Root
          value={p.preset}
          onValueChange={(v) => v !== "custom" && save.mutate(d.presets[v])}
          style={{ alignSelf: "flex-start" }}
        >
          <SegmentedControl.Item value="balanced">Balanced</SegmentedControl.Item>
          <SegmentedControl.Item value="max">Max performance</SegmentedControl.Item>
          <SegmentedControl.Item value="low">Low impact</SegmentedControl.Item>
          <SegmentedControl.Item value="custom">Custom</SegmentedControl.Item>
        </SegmentedControl.Root>
        <Text size={type.caption} color="gray">
          {PRESET_TEXT[p.preset]}
        </Text>
        <Flex gap={space.group} wrap="wrap">
          {field("Subjects at once", "max_subjects", "in a batch")}
          {field("Threads per job", "threads_per_job", "asked of each tool")}
          {field("Busy cores (total)", "cpu_cap", "at most")}
          {field("Memory kept free (GB)", "memory_reserve_gb", "for everything else", 0.5)}
        </Flex>
        <Text size={type.caption} color="gray">
          {Math.max(1, Math.floor(p.cpu_cap / p.threads_per_job))} processing job(s) can run at the same time. Some FSL tools start
          extra processes of their own; this limit cannot hold those back.
        </Text>
      </Flex>
    </Card>
  );
}

/** When MRForge flags a subject's head motion. It only flags; the decision is yours. */
function MotionFlagCard() {
  const client = useQueryClient();
  const q = useQuery({ queryKey: ["qc-settings"], queryFn: () => call(api.GET("/api/qc-settings")) });
  const save = useMutation({
    mutationFn: (t: MotionThresholds) => call(api.PUT("/api/qc-settings", { body: t })),
    onSuccess: () => client.invalidateQueries(),
  });
  const t = q.data;
  if (!t) return null;
  return (
    <Card size="3">
      <Flex direction="column" gap={space.group}>
        <Heading as="h2" size={type.sectionTitle}>
          Head-motion flag
        </Heading>
        <Text size={type.help} color="gray">
          A subject is flagged "check motion" when its mean framewise displacement is above the first number, or the share of
          volumes above 0.5 mm is above the second. A flag only asks you to look; MRForge never excludes anyone by itself.
        </Text>
        <Flex gap={space.group} wrap="wrap">
          <Flex direction="column" gap="1" style={{ width: 200 }}>
            <Text size={type.help} weight="medium">
              Mean FD above (mm)
            </Text>
            <TextField.Root
              type="number"
              step="0.05"
              min="0.05"
              value={String(t.mean_fd_mm)}
              onChange={(e) => Number(e.target.value) > 0 && save.mutate({ ...t, mean_fd_mm: Number(e.target.value) })}
            />
          </Flex>
          <Flex direction="column" gap="1" style={{ width: 200 }}>
            <Text size={type.help} weight="medium">
              Share of volumes above (%)
            </Text>
            <TextField.Root
              type="number"
              step="5"
              min="1"
              max="100"
              value={String(Math.round(t.fraction_above * 100))}
              onChange={(e) => {
                const v = Number(e.target.value) / 100;
                if (v > 0 && v <= 1) save.mutate({ ...t, fraction_above: v });
              }}
            />
          </Flex>
        </Flex>
      </Flex>
    </Card>
  );
}

export function Settings() {
  const { mode, setMode } = useAppTheme();
  const health = useQuery({ queryKey: ["health"], queryFn: () => call(api.GET("/api/health")) });
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader title="Settings" description="How MRForge looks, and which tools it found on this computer." />
      <Card size="3">
        <Flex direction="column" gap={space.group}>
          <Heading as="h2" size={type.sectionTitle}>Appearance</Heading>
          <SegmentedControl.Root value={mode} onValueChange={(v) => setMode(v as Mode)} style={{ alignSelf: "flex-start" }}>
            <SegmentedControl.Item value="light">Light</SegmentedControl.Item>
            <SegmentedControl.Item value="dark">Dark</SegmentedControl.Item>
            <SegmentedControl.Item value="system">Follow my computer</SegmentedControl.Item>
          </SegmentedControl.Root>
        </Flex>
      </Card>
      <ResourcesCard />
      <MotionFlagCard />
      <Card size="3">
        <Flex direction="column" gap={space.group}>
          <Heading as="h2" size={type.sectionTitle}>Tools and folders</Heading>
          <Text size={type.help} color="gray">
            The full check, with what to do about anything missing, is on the <a href="#/system">System page</a>.
          </Text>
          {health.error && <ErrorCallout error={(health.error as ApiError).body} />}
          {health.data && (
            <>
              <Table.Root>
                <Table.Body>
                  {Object.entries(health.data.tools).map(([key, version]) => (
                    <Table.Row key={key}>
                      <Table.RowHeaderCell>{toolName[key] ?? key}</Table.RowHeaderCell>
                      <Table.Cell>
                        {version ? (
                          <Badge color="green" variant="soft">
                            Found{version !== "installed" ? `, version ${version}` : ""}
                          </Badge>
                        ) : (
                          <Badge color={key === "ica-aroma" ? "gray" : "red"} variant="soft">
                            {key === "ica-aroma" ? "Not installed (optional)" : "Not found"}
                          </Badge>
                        )}
                      </Table.Cell>
                    </Table.Row>
                  ))}
                  <Table.Row>
                    <Table.RowHeaderCell>Workspaces folder</Table.RowHeaderCell>
                    <Table.Cell>
                      <Text size={type.help}>{health.data.workspaces_root}</Text>
                    </Table.Cell>
                  </Table.Row>
                  {health.data.disk_free_gb != null && (
                    <Table.Row>
                      <Table.RowHeaderCell>Free disk space</Table.RowHeaderCell>
                      <Table.Cell>
                        <Badge color={health.data.disk_free_gb < 20 ? "orange" : "green"} variant="soft">
                          {health.data.disk_free_gb} GB free
                          {health.data.disk_total_gb ? ` of ${health.data.disk_total_gb} GB` : ""}
                        </Badge>
                        {health.data.disk_free_gb < 20 && (
                          <Text size={type.help} ml="2">
                            Low: full processing of one subject can need several GB.
                          </Text>
                        )}
                      </Table.Cell>
                    </Table.Row>
                  )}
                  {health.data.cpu_cores != null && (
                    <Table.Row>
                      <Table.RowHeaderCell>Processor cores</Table.RowHeaderCell>
                      <Table.Cell>
                        <Text size={type.help}>{health.data.cpu_cores}</Text>
                      </Table.Cell>
                    </Table.Row>
                  )}
                  <Table.Row>
                    <Table.RowHeaderCell>MRForge version</Table.RowHeaderCell>
                    <Table.Cell>
                      <Text size={type.help}>{health.data.version}</Text>
                    </Table.Cell>
                  </Table.Row>
                </Table.Body>
              </Table.Root>
            </>
          )}
        </Flex>
      </Card>
    </Flex>
  );
}
