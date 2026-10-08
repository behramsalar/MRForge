import { DownloadIcon, MagnifyingGlassIcon } from "@radix-ui/react-icons";
import { Badge, Button, Callout, Card, Code, Flex, Grid, Heading, Table, Text } from "@radix-ui/themes";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { ReportQc, ReportRun } from "../api/types";
import { helpFor } from "../lib/qcHelp";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

const LAYER_NAMES: Record<string, string> = {
  functional: "Functional image, white-matter boundary in red",
  t1: "T1 image, edges of the functional image in red",
  before: "Before distortion correction",
  after: "After distortion correction",
  mni: "Mean functional image, outline of the standard brain in red",
};

/** The slices of one picture in a fixed layout: per layer, three columns (sagittal, coronal,
 * axial) of four slices each (2 by 2). Without kept slices, the joined picture, full width. */
function Pictures({ ws, qc }: { ws: string; qc: ReportQc }) {
  const url = (rel: string) => `/api/workspaces/${ws}/file/${rel}`;
  const layers = new Map<string, string[]>();
  for (const s of qc.slices) layers.set(s.layer, [...(layers.get(s.layer) ?? []), s.image]);
  if (layers.size === 0 && !qc.image) return null;
  return (
    <Flex direction="column" gap="2">
      <Text size={type.help} weight="medium">
        {qc.name}
      </Text>
      {layers.size === 0 ? (
        <a href={url(qc.image!)} target="_blank" rel="noreferrer">
          <img src={url(qc.image!)} alt={qc.name} style={{ width: "100%", display: "block", background: "black", borderRadius: "var(--radius-3)" }} />
        </a>
      ) : (
        [...layers.entries()].map(([layer, paths]) => (
          <Flex key={layer} direction="column" gap="1">
            <Text size={type.caption} color="gray">
              {LAYER_NAMES[layer] ?? layer}
            </Text>
            <Grid columns={{ initial: "1", sm: "3" }} gap="2">
              {[0, 4, 8].map((from) => (
                <Grid key={from} columns="2" gap="1" align="center" style={{ background: "black", padding: "var(--space-1)", borderRadius: "var(--radius-3)" }}>
                  {paths.slice(from, from + 4).map((p) => (
                    <a key={p} href={url(p)} target="_blank" rel="noreferrer">
                      <img src={url(p)} alt={qc.name} style={{ width: "100%", display: "block" }} />
                    </a>
                  ))}
                </Grid>
              ))}
            </Grid>
          </Flex>
        ))
      )}
      {helpFor(qc.name) && (
        <Text size={type.caption} color="gray">
          {helpFor(qc.name)}
        </Text>
      )}
    </Flex>
  );
}

function RunCard({ ws, subject, run }: { ws: string; subject: string; run: ReportRun }) {
  const metrics = run.qc.filter((q) => q.kind === "metric");
  const pictures = run.qc.filter((q) => q.kind !== "metric");
  return (
    <Card>
      <Flex direction="column" gap={space.group}>
        <Flex align="center" gap={space.inline} wrap="wrap">
          <Text weight="bold">{run.title}</Text>
          {run.recording && (
            <Badge variant="soft" color="gray">
              {run.recording}
            </Badge>
          )}
          {run.step === "func_qc" && (
            <Button size="1" variant="soft" className="no-print" asChild>
              <a href={href(ws, "viewer", subject)}>
                <MagnifyingGlassIcon /> Open interactively
              </a>
            </Button>
          )}
        </Flex>
        <Text size={type.caption} color="gray">
          Step version {run.step_version}
          {run.finished ? `, finished ${new Date(run.finished).toLocaleString()}` : ""}
          {run.started_by ? `, started by ${run.started_by}` : ""}
        </Text>
        {metrics.length > 0 && (
          <Table.Root size="1">
            <Table.Body>
              {metrics.map((m) => (
                <Table.Row key={m.name}>
                  <Table.RowHeaderCell>{m.name}</Table.RowHeaderCell>
                  <Table.Cell>{m.value}</Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table.Root>
        )}
        {pictures.map((q) => (
          <Pictures key={q.name} ws={ws} qc={q} />
        ))}
        {run.warnings.map((w) => (
          <Callout.Root key={w} color="amber" size="1">
            <Callout.Text>{w}</Callout.Text>
          </Callout.Root>
        ))}
        <details>
          <summary>
            <Text size={type.help}>Parameters and commands</Text>
          </summary>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: "var(--font-size-1)" }}>{JSON.stringify(run.parameters, null, 2)}</pre>
          {run.commands.length === 0 ? (
            <Text size={type.caption} color="gray">
              No external command was recorded.
            </Text>
          ) : (
            run.commands.map((c, n) => (
              <Flex key={n} direction="column" gap="1" mb="2">
                <Code style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{c.command}</Code>
                <Text size={type.caption} color="gray">
                  exit code {c.return_code}
                </Text>
              </Flex>
            ))
          )}
          <Text size={type.caption} color="gray">
            {run.inputs} input and {run.outputs} output files, with hashes, are in {run.run_dir}/provenance.json
          </Text>
        </details>
      </Flex>
    </Card>
  );
}

/** The report of one subject: what was done, with what settings, what the checks say, in
 * reading order. Built by the server only from what was recorded. */
export function ReportView({ ws, subject }: { ws: string; subject: string }) {
  const report = useQuery({
    queryKey: ["ws", ws, "report", subject],
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/subjects/{label}/report", { params: { path: { ws_id: ws, label: subject } } })),
  });
  const save = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/subjects/{label}/report/export", {
          params: { path: { ws_id: ws, label: subject } },
        }),
      ),
  });
  if (report.error) return <ErrorCallout error={(report.error as ApiError).body} />;
  const r = report.data;
  if (!r) return null;
  const last = r.decisions[r.decisions.length - 1];
  return (
    <Flex direction="column" gap={space.group}>
      <Flex justify="between" align="center" wrap="wrap" gap={space.group}>
        <Heading as="h2" size={type.sectionTitle}>
          Report
        </Heading>
        <Flex gap={space.group} className="no-print">
          <Button variant="soft" onClick={() => window.print()}>
            Print
          </Button>
          <Button disabled={save.isPending} onClick={() => save.mutate()}>
            <DownloadIcon /> Save report as HTML
          </Button>
        </Flex>
      </Flex>
      <Text size={type.help} color="gray">
        Built from what MRForge recorded for {subject}, nothing estimated. Save it as an HTML file to keep a copy or send it to a colleague.
      </Text>
      {save.error && <ErrorCallout error={(save.error as ApiError).body} />}
      {save.data && (
        <Callout.Root color="green" size="1">
          <Callout.Text>
            Saved as <Code>reports/{subject}/{save.data.name}</Code>.{" "}
            <a href={save.data.url} target="_blank" rel="noreferrer">
              Open it
            </a>
          </Callout.Text>
        </Callout.Root>
      )}
      {last && (
        <Card>
          <Flex direction="column" gap="1">
            <Text weight="bold">Quality decision</Text>
            <Text size={type.help}>
              <Badge color={last.decision === "accept" ? "green" : last.decision === "exclude" ? "red" : "amber"} variant="soft">
                {last.decision}
              </Badge>{" "}
              {last.reason} ({last.who ?? "unknown"}, {new Date(last.when).toLocaleString()})
            </Text>
            {r.decisions.length > 1 && (
              <Text size={type.caption} color="gray">
                {r.decisions.length - 1} earlier decision(s) are kept in the saved report.
              </Text>
            )}
          </Flex>
        </Card>
      )}
      {r.warnings.length > 0 && (
        <Callout.Root color="amber">
          <Callout.Text>
            {r.warnings.length} {r.warnings.length === 1 ? "warning" : "warnings"}: {r.warnings.join(" · ")}
          </Callout.Text>
        </Callout.Root>
      )}
      <Heading as="h3" size={type.sectionTitle}>
        Acquisition
      </Heading>
      {r.acquisition.length === 0 ? (
        <Text size={type.help} color="gray">
          No imported series are recorded for this subject.
        </Text>
      ) : (
        <Table.Root size="1">
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeaderCell>Series</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Description</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Imported as</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Size</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Volumes</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>TR / TE (s)</Table.ColumnHeaderCell>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {r.acquisition.map((a) => (
              <Table.Row key={`${a.import_id}-${a.number}-${a.description}`}>
                <Table.Cell>{a.number}</Table.Cell>
                <Table.Cell>{a.description}</Table.Cell>
                <Table.Cell>{a.kind}</Table.Cell>
                <Table.Cell>{a.matrix}</Table.Cell>
                <Table.Cell>{a.volumes}</Table.Cell>
                <Table.Cell>
                  {a.repetition_time_s ?? "-"} / {a.echo_time_s ?? "-"}
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Root>
      )}
      {r.sections.map((s) => (
        <Flex key={s.id} direction="column" gap={space.group}>
          <Heading as="h3" size={type.sectionTitle}>
            {s.title}
          </Heading>
          {s.runs.map((run) => (
            <RunCard key={run.job_id} ws={ws} subject={subject} run={run} />
          ))}
          {s.not_run.length > 0 && (
            <Text size={type.help} color="gray">
              Not run: {s.not_run.join(", ")}
            </Text>
          )}
        </Flex>
      ))}
      <Heading as="h3" size={type.sectionTitle}>
        Software
      </Heading>
      <Text size={type.help}>{Object.entries(r.software).map(([k, v]) => `${k} ${v}`).join(" · ")}</Text>
    </Flex>
  );
}
