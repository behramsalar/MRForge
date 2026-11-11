import { CheckIcon, ChevronLeftIcon, ChevronRightIcon, Cross2Icon, EyeOpenIcon, FileTextIcon } from "@radix-ui/react-icons";
import { Badge, Button, Callout, Dialog, Flex, Grid, SegmentedControl, Table, Text, TextField } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { Overview } from "../api/types";
import { helpFor } from "../lib/qcHelp";
import { CHECKS, afterDecision, findQc, type CheckId } from "../lib/qualityReview";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";
import { useSubjectReport } from "./QualityGrid";
import { DECISION_COLOUR, DECISION_LABEL, QUICK_REASONS } from "./QualityDecisionCard";

type Row = Overview["subjects"][number];
type Choice = "accept" | "review" | "exclude";
const KEY: Record<string, Choice> = { a: "accept", r: "review", x: "exclude" };
const ICON = { accept: <CheckIcon />, review: <EyeOpenIcon />, exclude: <Cross2Icon /> };
const BUTTON = { accept: "Accept", review: "Mark for review", exclude: "Exclude" };

/** One subject, large: the pictures of the chosen check, the numbers, and the decision. Arrow
 * keys (or j / k) move through the list, a / r / x choose a decision, 1 to 4 switch the check.
 * Every decision needs a reason and is the researcher's alone. */
export function QualityInspector({
  ws,
  rows,
  labels,
  current,
  check,
  onCheck,
  onNavigate,
  onClose,
}: {
  ws: string;
  rows: Row[];
  labels: string[];
  current: string | null;
  check: CheckId;
  onCheck: (c: CheckId) => void;
  onNavigate: (label: string | null) => void;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const row = rows.find((r) => r.label === current);
  const report = useSubjectReport(ws, current ?? "", !!current);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [reason, setReason] = useState("");
  useEffect(() => {
    setChoice(null);
    setReason("");
  }, [current]);
  const save = useMutation({
    mutationFn: (c: Choice) =>
      call(api.PUT("/api/workspaces/{ws_id}/subjects/{label}/qc-decision", { params: { path: { ws_id: ws, label: current! } }, body: { decision: c, reason } })),
    onSuccess: () => {
      const next = afterDecision(labels, current!);
      void client.invalidateQueries({ queryKey: ["ws", ws] });
      onNavigate(next);
    },
  });
  const i = current ? labels.indexOf(current) : -1;
  const go = (d: number) => {
    const t = labels[i + d];
    if (t) onNavigate(t);
  };
  useEffect(() => {
    if (!current) return;
    const on = (e: KeyboardEvent) => {
      const t = e.target instanceof Element ? e.target : null;
      if (e.metaKey || e.ctrlKey || e.altKey || t?.closest("input, textarea, [contenteditable]")) return;
      if (e.key === "ArrowRight" || e.key === "j") go(1);
      else if (e.key === "ArrowLeft" || e.key === "k") go(-1);
      else if (KEY[e.key.toLowerCase()]) {
        e.preventDefault();
        setChoice(KEY[e.key.toLowerCase()]);
      } else if (/^[1-4]$/.test(e.key)) onCheck(CHECKS[Number(e.key) - 1].id);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });
  const found = findQc(report.data, check);
  const currentDecision = row?.qc_decision as Choice | null | undefined;
  return (
    <Dialog.Root open={!!current} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Content
        maxWidth="1000px"
        aria-describedby={undefined}
        onEscapeKeyDown={(e) => {
          if (choice) {
            e.preventDefault();
            setChoice(null);
          }
        }}
      >
        <Flex justify="between" align="center" gap={space.group} wrap="wrap">
          <Flex align="center" gap={space.group}>
            <Dialog.Title mb="0">{current}</Dialog.Title>
            {currentDecision && (
              <Badge color={DECISION_COLOUR[currentDecision]} variant="soft" title={row?.qc_reason ?? undefined}>
                {DECISION_LABEL[currentDecision]}
              </Badge>
            )}
            {row?.motion_flag && (
              <Badge color="amber" variant="soft">
                {row.motion_flag}
              </Badge>
            )}
          </Flex>
          <Flex align="center" gap="2">
            <Text size={type.caption} color="gray">
              {i >= 0 ? `${i + 1} of ${labels.length}` : "not in this list"}
            </Text>
            <Button size="1" variant="soft" color="gray" disabled={i <= 0} onClick={() => go(-1)} aria-label="Previous subject">
              <ChevronLeftIcon />
            </Button>
            <Button size="1" variant="soft" color="gray" disabled={i < 0 || i >= labels.length - 1} onClick={() => go(1)} aria-label="Next subject">
              <ChevronRightIcon />
            </Button>
            <Dialog.Close>
              <Button size="1" variant="ghost" color="gray" aria-label="Close">
                <Cross2Icon />
              </Button>
            </Dialog.Close>
          </Flex>
        </Flex>
        <Flex direction="column" gap={space.group} mt="3" style={{ maxHeight: "68vh", overflowY: "auto", paddingRight: 4 }}>
          <SegmentedControl.Root size="1" value={check} onValueChange={(v) => onCheck(v as CheckId)} style={{ alignSelf: "flex-start" }}>
            {CHECKS.map((c, n) => (
              <SegmentedControl.Item key={c.id} value={c.id}>
                {c.label} <kbd className="kbd">{n + 1}</kbd>
              </SegmentedControl.Item>
            ))}
          </SegmentedControl.Root>
          {report.error && <ErrorCallout error={(report.error as ApiError).body} />}
          {report.isLoading && <Text color="gray">Loading the checks…</Text>}
          {report.data && found.length === 0 && (
            <Text color="gray" size={type.help}>
              This subject has no result for this check (the step has not run, or the data has no field map).
            </Text>
          )}
          {found.map(({ run, qc }, n) => {
            const layers = new Map<string, string[]>();
            for (const s of qc.slices) layers.set(s.layer, [...(layers.get(s.layer) ?? []), s.image]);
            const url = (p: string) => `/api/workspaces/${ws}/file/${p}`;
            return (
              <Flex key={`${run.job_id}:${n}`} direction="column" gap="2">
                <Text size={type.help} weight="medium">
                  {qc.name}
                  {run.recording ? ` · ${run.recording}` : ""}
                </Text>
                {qc.image ? (
                  <div className="qi-pics">
                    <img src={url(qc.image)} alt={qc.name} />
                  </div>
                ) : (
                  [...layers.values()].map((paths, k) => (
                    <Grid key={k} columns="3" gap="1">
                      {[0, 4, 8].map((from) => (
                        <Grid key={from} columns="2" gap="1" className="qi-pics">
                          {paths.slice(from, from + 4).map((p) => (
                            <img key={p} src={url(p)} alt={qc.name} />
                          ))}
                        </Grid>
                      ))}
                    </Grid>
                  ))
                )}
                {helpFor(qc.name) && (
                  <Text size={type.caption} color="gray">
                    {helpFor(qc.name)}
                  </Text>
                )}
                {run.qc.filter((q) => q.kind === "metric").length > 0 && (
                  <Table.Root size="1">
                    <Table.Body>
                      {run.qc
                        .filter((q) => q.kind === "metric")
                        .map((m) => (
                          <Table.Row key={m.name}>
                            <Table.RowHeaderCell>{m.name}</Table.RowHeaderCell>
                            <Table.Cell>{m.value}</Table.Cell>
                          </Table.Row>
                        ))}
                    </Table.Body>
                  </Table.Root>
                )}
                {qc.warning && (
                  <Callout.Root color="amber" size="1">
                    <Callout.Text>{qc.warning}</Callout.Text>
                  </Callout.Root>
                )}
              </Flex>
            );
          })}
        </Flex>
        <Flex direction="column" gap="2" mt="4" pt="3" style={{ borderTop: "1px solid var(--gray-a5)" }}>
          <Flex gap="2" wrap="wrap" align="center">
            {(["accept", "review", "exclude"] as Choice[]).map((c) => (
              <Button key={c} size="2" variant={choice === c || (!choice && currentDecision === c) ? "solid" : "soft"} color={DECISION_COLOUR[c]} onClick={() => setChoice(c)}>
                {ICON[c]} {BUTTON[c]} <kbd className="kbd">{c === "accept" ? "A" : c === "review" ? "R" : "X"}</kbd>
              </Button>
            ))}
            <span style={{ flex: 1 }} />
            <Button size="2" variant="outline" asChild>
              <a href={href(ws, "viewer", current ?? "")}>
                <EyeOpenIcon /> Open in viewer
              </a>
            </Button>
            <Button size="2" variant="soft" asChild>
              <a href={href(ws, "subject", current ?? "", "results")}>
                <FileTextIcon /> Full report
              </a>
            </Button>
          </Flex>
          {choice && (
            <Flex direction="column" gap="2">
              <Flex gap="1" wrap="wrap">
                {QUICK_REASONS[choice].map((q) => (
                  <Button key={q} size="1" variant="soft" color="gray" onClick={() => setReason(q)}>
                    {q}
                  </Button>
                ))}
              </Flex>
              <Flex gap="2">
                <TextField.Root
                  style={{ flex: 1 }}
                  placeholder={`Why? (kept with your name and the date) Enter saves, Esc cancels`}
                  value={reason}
                  autoFocus
                  aria-label="Reason"
                  onChange={(e) => setReason(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && reason.trim() && !save.isPending) save.mutate(choice);
                  }}
                />
                <Button disabled={!reason.trim() || save.isPending} color={DECISION_COLOUR[choice]} onClick={() => save.mutate(choice)}>
                  Save {BUTTON[choice].toLowerCase()}
                </Button>
              </Flex>
              {choice === "exclude" && (
                <Text size={type.caption} color="gray">
                  An excluded subject is left out of the analysis-ready folder and unticked in batches. You can change this later.
                </Text>
              )}
            </Flex>
          )}
          {save.error && <ErrorCallout error={(save.error as ApiError).body} />}
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
