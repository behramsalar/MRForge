import { ChevronLeftIcon, ChevronRightIcon, DownloadIcon, EyeClosedIcon, EyeOpenIcon, MagnifyingGlassIcon } from "@radix-ui/react-icons";
import { Badge, Button, Callout, Card, Code, Flex, Heading, IconButton, Table, Text } from "@radix-ui/themes";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { ReportQc, ReportRun } from "../api/types";
import { helpFor } from "../lib/qcHelp";
import { type LayoutItem, type Size, arrange, move, nextSize, resize, setHidden } from "../lib/reportLayout";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

const TILE: Record<Size, string> = { s: "110px", m: "190px", l: "300px" };
const WIDE: Record<Size, string> = { s: "40%", m: "70%", l: "100%" };
const SIZE_WORD: Record<Size, string> = { s: "Small", m: "Medium", l: "Large" };

type Layout = { items: LayoutItem[]; set: (items: LayoutItem[]) => void };

/** The arrangement is the researcher's; it is remembered in this browser (a convenience) and
 * saved with every exported report, which is where it is restored from on another computer. */
function useLayout(ws: string, subject: string): Layout {
  const key = `mrforge.reportLayout.${ws}.${subject}`;
  const saved = useQuery({
    queryKey: ["ws", ws, "report-layout", subject],
    queryFn: () =>
      call(api.GET("/api/workspaces/{ws_id}/subjects/{label}/report/layout", { params: { path: { ws_id: ws, label: subject } } })),
  });
  const [items, setItems] = useState<LayoutItem[] | null>(null);
  useEffect(() => {
    if (items !== null || saved.isLoading) return;
    let local: LayoutItem[] | null = null;
    try {
      const raw = localStorage.getItem(key);
      if (raw) local = JSON.parse(raw) as LayoutItem[];
    } catch {
      local = null;
    }
    setItems(local ?? (saved.data?.items as LayoutItem[] | undefined) ?? []);
  }, [items, saved.isLoading, saved.data, key]);
  return {
    items: items ?? [],
    set: (next) => {
      setItems(next);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // private window or blocked storage: the arrangement just is not remembered
      }
    },
  };
}

function PictureControls({
  name,
  size,
  first,
  last,
  onMove,
  onSize,
  onHide,
}: {
  name: string;
  size: Size;
  first: boolean;
  last: boolean;
  onMove: (d: -1 | 1) => void;
  onSize: () => void;
  onHide: () => void;
}) {
  return (
    <Flex gap="1" align="center" justify="center" className="no-print">
      <IconButton size="1" variant="ghost" color="gray" disabled={first} aria-label={`Move ${name} earlier`} onClick={() => onMove(-1)}>
        <ChevronLeftIcon />
      </IconButton>
      <Button size="1" variant="ghost" color="gray" aria-label={`Size of ${name}: ${SIZE_WORD[size]}. Press to change`} onClick={onSize}>
        {SIZE_WORD[size]}
      </Button>
      <IconButton size="1" variant="ghost" color="gray" aria-label={`Hide ${name}`} onClick={onHide}>
        <EyeClosedIcon />
      </IconButton>
      <IconButton size="1" variant="ghost" color="gray" disabled={last} aria-label={`Move ${name} later`} onClick={() => onMove(1)}>
        <ChevronRightIcon />
      </IconButton>
    </Flex>
  );
}

function Pictures({ ws, qc, layout }: { ws: string; qc: ReportQc; layout: Layout }) {
  const wide = qc.slices.length === 0;
  const paths = wide ? (qc.image ? [qc.image] : []) : qc.slices.map((s) => s.image);
  const dflt: Size = wide ? "l" : "m";
  const arranged = arrange(paths, layout.items, dflt);
  const shown = arranged.filter((p) => !p.hidden);
  const hidden = arranged.filter((p) => p.hidden);
  const layerOf = new Map(qc.slices.map((s) => [s.image, s.layer]));
  const url = (rel: string) => `/api/workspaces/${ws}/file/${rel}`;
  if (paths.length === 0) return null;
  return (
    <Flex direction="column" gap="2">
      <Text size={type.help} weight="medium">
        {qc.name}
      </Text>
      <Flex wrap="wrap" gap="2" style={{ background: "black", padding: "var(--space-2)", borderRadius: "var(--radius-3)" }}>
        {shown.map((p, n) => (
          <Flex key={p.image} direction="column" gap="1" style={{ width: wide ? WIDE[p.size] : TILE[p.size] }}>
            <a href={url(p.image)} target="_blank" rel="noreferrer">
              <img src={url(p.image)} alt={qc.name} style={{ width: "100%", display: "block", borderRadius: "var(--radius-2)" }} />
            </a>
            {layerOf.get(p.image) && (
              <Text size="1" style={{ color: "white", opacity: 0.7 }}>
                {layerOf.get(p.image)}
              </Text>
            )}
            <PictureControls
              name={qc.name}
              size={p.size}
              first={n === 0}
              last={n === shown.length - 1}
              onMove={(d) => layout.set(move(layout.items, paths, p.image, d, dflt))}
              onSize={() => layout.set(resize(layout.items, paths, p.image, nextSize(p.size), dflt))}
              onHide={() => layout.set(setHidden(layout.items, paths, p.image, true, dflt))}
            />
          </Flex>
        ))}
      </Flex>
      {hidden.length > 0 && (
        <Flex gap="2" align="center" wrap="wrap" className="no-print">
          <Text size={type.caption} color="gray">
            Hidden ({hidden.length}):
          </Text>
          {hidden.map((p) => (
            <Button key={p.image} size="1" variant="soft" color="gray" onClick={() => layout.set(setHidden(layout.items, paths, p.image, false, dflt))}>
              <EyeOpenIcon /> {p.image.split("/").pop()?.replace(/\.png$/, "")}
            </Button>
          ))}
        </Flex>
      )}
      {helpFor(qc.name) && (
        <Text size={type.caption} color="gray">
          {helpFor(qc.name)}
        </Text>
      )}
    </Flex>
  );
}

function RunCard({ ws, subject, run, layout }: { ws: string; subject: string; run: ReportRun; layout: Layout }) {
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
          <Pictures key={q.name} ws={ws} qc={q} layout={layout} />
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
  const layout = useLayout(ws, subject);
  const save = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/subjects/{label}/report/export", {
          params: { path: { ws_id: ws, label: subject } },
          body: { items: layout.items.map((i) => ({ image: i.image, hidden: i.hidden ?? false, size: i.size ?? "m" })) },
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
        Built from what MRForge recorded for {subject}, nothing estimated. You can reorder, resize and hide the pictures; the saved HTML
        file keeps your arrangement.
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
            <RunCard key={run.job_id} ws={ws} subject={subject} run={run} layout={layout} />
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
