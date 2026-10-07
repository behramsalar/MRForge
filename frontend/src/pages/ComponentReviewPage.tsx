import { CheckIcon } from "@radix-ui/react-icons";
import {
  AlertDialog,
  Badge,
  Button,
  Callout,
  Card,
  Flex,
  Heading,
  ScrollArea,
  SegmentedControl,
  Select,
  Slider,
  Text,
} from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useSubjects } from "../api/hooks";
import type { IcaComponent } from "../api/types";
import { ErrorCallout } from "../components/ErrorCallout";
import { Viewer } from "../components/Viewer";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { LABEL_COLOURS, LABEL_NAMES, counts, nextUnlabelled, noiseList, toLabels, type IcaLabel, type Labels } from "../lib/icaLabels";
import { when } from "../lib/labels";
import { space, type } from "../theme/tokens";
import { useWorkspace } from "../shell/WorkspaceContext";
import { ConfirmProcessDialog } from "../components/ConfirmProcessDialog";

const Z_DEFAULT = 2.3; // REVIEW(domain): the common display threshold for MELODIC z-maps

function Dot({ label }: { label?: IcaLabel }) {
  return (
    <span
      aria-hidden
      style={{
        width: 10,
        height: 10,
        borderRadius: "50%",
        flex: "none",
        background: label ? `var(--${LABEL_COLOURS[label]}-9)` : "transparent",
        border: label ? "none" : "1px solid var(--gray-8)",
      }}
    />
  );
}

/**
 * Artifact rejection: look at each component MELODIC found (brain map in the viewer, slice
 * summary, time course and frequencies) and label it signal, noise or uncertain. MRForge only
 * shows; the decision is yours. Saving the final decision lets a waiting pipeline carry on.
 */
export function ComponentReviewPage({ ws }: { ws: string }) {
  const queryClient = useQueryClient();
  const { state } = useWorkspace();
  const subjects = useSubjects(ws);
  const [subject, setSubject] = useState<string | undefined>();
  const label = subject ?? subjects.data?.[0]?.label;
  const results = useQuery({
    queryKey: ["ws", ws, "ica", label],
    enabled: !!label,
    queryFn: () =>
      call(api.GET("/api/workspaces/{ws_id}/subjects/{label}/ica", { params: { path: { ws_id: ws, label: label! } } })),
  });
  const recordings = results.data ?? [];
  const [recIndex, setRecIndex] = useState(0);
  const rec = recordings[Math.min(recIndex, recordings.length - 1)];
  const [number, setNumber] = useState(1);
  const [z, setZ] = useState(Z_DEFAULT);
  const [labels, setLabels] = useState<Labels>({});
  const [editing, setEditing] = useState(false); // changing a decision that was already made
  const [draftState, setDraftState] = useState<"" | "saving" | "saved">("");
  const savedKey = useRef("");

  const decided = rec?.label_status === "decided";
  const locked = decided && !editing;
  const total = rec?.n_components ?? 0;

  // Start from what is saved (a draft, or the decision) whenever the recording changes.
  // (Not when a refetch only says "draft" instead of "none": that would wipe what is being typed.)
  useEffect(() => {
    setNumber(1);
  }, [rec?.recording, label]);
  useEffect(() => {
    setEditing(false);
    const saved = toLabels(rec?.labels ?? {});
    const proposal = toLabels(rec?.proposal ?? {});
    // Nothing of yours saved yet: start from ICA-AROMA's proposal if there is one. It is not
    // saved as a draft (savedKey) until you change something, and nothing is final until you
    // press Save and continue.
    const initial = Object.keys(saved).length === 0 ? proposal : saved;
    setLabels(initial);
    savedKey.current = JSON.stringify(initial);
  }, [rec?.recording, label, decided]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: (args: { labels: Labels; complete: boolean }) =>
      call(
        api.PUT("/api/workspaces/{ws_id}/subjects/{label}/ica/{recording}/labels", {
          params: { path: { ws_id: ws, label: label!, recording: rec!.recording } },
          body: { labels: args.labels as unknown as Record<string, string>, complete: args.complete },
        }),
      ),
  });
  const resume = useMutation({
    mutationFn: () => call(api.POST("/api/workspaces/{ws_id}/resume", { params: { path: { ws_id: ws } } })),
  });

  // A draft is saved a moment after every change, so nothing is lost on reload or on a crash.
  useEffect(() => {
    if (!rec || locked || editing) return;
    const key = JSON.stringify(labels);
    if (key === savedKey.current || Object.keys(labels).length === 0) return;
    const timer = setTimeout(() => {
      setDraftState("saving");
      save.mutate(
        { labels, complete: false },
        {
          onSuccess: () => {
            savedKey.current = key;
            setDraftState("saved");
          },
          onError: () => setDraftState(""),
        },
      );
    }, 700);
    return () => clearTimeout(timer);
  }, [labels, locked, editing, rec]); // eslint-disable-line react-hooks/exhaustive-deps

  const current: IcaComponent | undefined = rec?.components.find((c) => c.number === number) ?? rec?.components[0];
  const n = useMemo(() => counts(labels, total), [labels, total]);
  const noise = useMemo(() => noiseList(labels), [labels]);
  const waiting = state?.operations.some((o) => o.status === "Waiting") ?? false;

  const choose = (choice: IcaLabel) => {
    if (!current || locked) return;
    const next = { ...labels, [current.number]: choice };
    setLabels(next);
    const after = nextUnlabelled(next, total, current.number);
    if (after && !labels[current.number]) setNumber(after); // moves on only when labelling for the first time
  };

  // Keys: arrows move, S / N / U label.
  useEffect(() => {
    if (!rec) return;
    const on = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "ArrowDown") setNumber((v) => Math.min(rec.n_components, v + 1));
      else if (e.key === "ArrowUp") setNumber((v) => Math.max(1, v - 1));
      else if (e.key.toLowerCase() === "s") choose("signal");
      else if (e.key.toLowerCase() === "n") choose("noise");
      else if (e.key.toLowerCase() === "u") choose("uncertain");
    };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  });

  const finish = async () => {
    await save.mutateAsync({ labels, complete: true });
    await queryClient.invalidateQueries({ queryKey: ["ws", ws, "ica", label] });
    if (waiting) await resume.mutateAsync();
    setEditing(false);
  };
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [runOpen, setRunOpen] = useState(false);
  const complete = n.unlabelled === 0 && total > 0;

  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader
        title="Artifact rejection"
        description="Look at each component MELODIC found and decide whether it is brain activity or noise."
      />
      <Flex gap={space.group} align="center" wrap="wrap">
        <Select.Root value={label} onValueChange={setSubject}>
          <Select.Trigger aria-label="Subject" />
          <Select.Content>
            {(subjects.data ?? []).map((s) => (
              <Select.Item key={s.label} value={s.label}>
                {s.label}
              </Select.Item>
            ))}
          </Select.Content>
        </Select.Root>
        {recordings.length > 1 && (
          <Select.Root value={String(recIndex)} onValueChange={(v) => setRecIndex(Number(v))}>
            <Select.Trigger aria-label="Recording" />
            <Select.Content>
              {recordings.map((r, i) => (
                <Select.Item key={r.recording} value={String(i)}>
                  {r.recording}
                </Select.Item>
              ))}
            </Select.Content>
          </Select.Root>
        )}
        {rec && (
          <Text size={type.help} color="gray">
            {rec.n_components} components from {rec.n_volumes} volumes (TR {rec.tr_s} s)
          </Text>
        )}
        {label && (
          <Button size="2" variant="soft" style={{ marginLeft: "auto" }} disabled={waiting} onClick={() => setRunOpen(true)}>
            {rec ? "Run artifact rejection again…" : "Run artifact rejection…"}
          </Button>
        )}
      </Flex>
      {label && <ConfirmProcessDialog ws={ws} subject={label} open={runOpen} onOpenChange={setRunOpen} onlyStage="artifact_rejection" />}
      {results.error && <ErrorCallout error={(results.error as ApiError).body} />}
      {results.data && !rec && (
        <EmptyState
          title="No components yet"
          text="Component analysis (MELODIC) has not been run for this subject. Use the button above to run artifact rejection (the preprocessing must be done first)."
        />
      )}
      {rec?.label_status === "stale" && (
        <Callout.Root color="amber">
          <Callout.Text>
            The components were found again (MELODIC was re-run), so the labels you made earlier no longer fit and are not used.
            Please label them again.
          </Callout.Text>
        </Callout.Root>
      )}
      {rec && !decided && Object.keys(rec.labels).length === 0 && Object.keys(rec.proposal).length > 0 && (
        <Callout.Root color="blue">
          <Callout.Text>
            The labels are filled in by {rec.proposal_source ?? "an automatic method"} as a proposal. Look at each component and change
            what you disagree with; nothing is final until you press Save and continue.
          </Callout.Text>
        </Callout.Root>
      )}
      {rec && decided && (
        <Callout.Root color="green">
          <Flex align="center" justify="between" gap={space.group} wrap="wrap" style={{ width: "100%" }}>
            <Text>
              Decision saved{rec.decided_by ? ` by ${rec.decided_by}` : ""}
              {rec.decided_at ? ` on ${when(rec.decided_at)}` : ""}: {n.noise} noise, {n.signal} signal, {n.uncertain} uncertain.
            </Text>
            {!editing && (
              <Button size="2" variant="soft" color="gray" onClick={() => setEditing(true)}>
                Change my decision
              </Button>
            )}
          </Flex>
        </Callout.Root>
      )}
      {rec && current && (
        <Flex gap={space.group} align="start" wrap="wrap">
          <Card size="2" style={{ flex: "0 0 230px" }}>
            <Heading as="h2" size={type.help} mb="2">
              Components
            </Heading>
            <ScrollArea style={{ maxHeight: "62vh" }}>
              <Flex direction="column" gap="1">
                {rec.components.map((c) => (
                  <button
                    key={c.number}
                    onClick={() => setNumber(c.number)}
                    aria-current={c.number === current.number ? "true" : undefined}
                    style={{
                      all: "unset",
                      cursor: "pointer",
                      padding: "var(--space-1) var(--space-2)",
                      borderRadius: "var(--radius-2)",
                      background: c.number === current.number ? "var(--accent-a4)" : undefined,
                      display: "flex",
                      alignItems: "center",
                      gap: "var(--space-2)",
                    }}
                  >
                    <Dot label={labels[c.number]} />
                    <Text size={type.help} style={{ flex: 1 }}>
                      Component {c.number}
                    </Text>
                    <Text size={type.caption} color="gray">
                      {c.variance_pct != null ? `${c.variance_pct.toFixed(1)}%` : ""}
                    </Text>
                  </button>
                ))}
              </Flex>
            </ScrollArea>
            <Text size={type.caption} color="gray" as="p" mt="2">
              Arrows move. S, N and U label the shown component.
            </Text>
          </Card>
          <Flex direction="column" gap={space.group} style={{ flex: "1 1 560px", minWidth: 0 }}>
            <Flex justify="between" align="center" wrap="wrap" gap={space.group}>
              <Heading as="h2" size={type.sectionTitle}>
                Component {current.number} of {rec.n_components}
              </Heading>
              <SegmentedControl.Root
                value={labels[current.number] ?? ""}
                onValueChange={(v) => choose(v as IcaLabel)}
                aria-label="Your label for this component"
              >
                {(Object.keys(LABEL_NAMES) as IcaLabel[]).map((l) => (
                  <SegmentedControl.Item key={l} value={l}>
                    {LABEL_NAMES[l]}
                  </SegmentedControl.Item>
                ))}
              </SegmentedControl.Root>
            </Flex>
            <Flex gap={space.inline} align="center" justify="end" wrap="wrap">
              <Badge color="orange" variant="soft">
                positive
              </Badge>
              <Badge color="blue" variant="soft">
                negative
              </Badge>
              <Text size={type.caption} color="gray">
                show strength above
              </Text>
              <Slider
                style={{ width: 140 }}
                min={1.5}
                max={5}
                step={0.1}
                value={[z]}
                onValueChange={(v) => setZ(v[0])}
                aria-label="Show strength above"
              />
              <Text size={type.help}>{z.toFixed(1)}</Text>
            </Flex>
            <Viewer
              underlay={rec.mean_url}
              overlays={[{ url: current.map_url, colormap: "hot", colormapNegative: "winter", opacity: 1, calMin: z, calMax: 8 }]}
              layout="row"
              height="44vh"
              crosshairMm={current.peak_mm}
            />
            <Card size="1">
              <img src={current.plots_url} alt={`Time course and frequencies of component ${current.number}`} style={{ width: "100%", display: "block" }} />
            </Card>
            <Card size="1" style={{ background: "black" }}>
              <img src={current.planes_url} alt={`Slices of component ${current.number} in three planes`} style={{ width: "100%", display: "block" }} />
            </Card>
            <Callout.Root color="gray" size="1">
              <Callout.Text>
                Noise often looks like: activity at the edge of the brain or in the ventricles, stripes, a sudden spike
                in the time course (head movement), or mostly fast frequencies. Real networks are in grey matter and
                slow (below 0.1 Hz). MRForge only shows; you decide.
              </Callout.Text>
            </Callout.Root>
          </Flex>
        </Flex>
      )}
      {rec && (
        <Card
          size="2"
          style={{ position: "sticky", bottom: "var(--space-3)", boxShadow: "var(--shadow-4)", zIndex: 2 }}
        >
          <Flex align="center" justify="between" gap={space.group} wrap="wrap">
            <Flex gap={space.group} align="center" wrap="wrap">
              <Badge color="green" variant="soft">{n.signal} signal</Badge>
              <Badge color="red" variant="soft">{n.noise} noise</Badge>
              <Badge color="amber" variant="soft">{n.uncertain} uncertain</Badge>
              <Badge color="gray" variant="soft">{n.unlabelled} not labelled</Badge>
              {n.unlabelled > 0 && (
                <Button size="1" variant="ghost" onClick={() => current && setNumber(nextUnlabelled(labels, total, current.number) ?? current.number)}>
                  Next unlabelled
                </Button>
              )}
              {!locked && draftState && (
                <Text size={type.caption} color="gray">
                  {draftState === "saving" ? "Saving draft…" : "Draft saved"}
                </Text>
              )}
            </Flex>
            <Flex gap={space.inline} align="center">
              {(save.error || resume.error) && (
                <Text size={type.help} color="red">
                  {((save.error ?? resume.error) as ApiError).body?.message}
                </Text>
              )}
              <Button size="3" disabled={locked || !complete || save.isPending} onClick={() => setConfirmOpen(true)}>
                <CheckIcon /> Save and continue
              </Button>
            </Flex>
          </Flex>
        </Card>
      )}
      <AlertDialog.Root open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialog.Content maxWidth="480px">
          <AlertDialog.Title>Save your decision?</AlertDialog.Title>
          <AlertDialog.Description size={type.help}>
            {noise.length === 0
              ? "You marked no component as noise: the data will be used as they are."
              : `${noise.length} component${noise.length === 1 ? "" : "s"} will be removed from the data: ${noise.join(", ")}.`}{" "}
            {n.uncertain > 0 && `${n.uncertain} uncertain component${n.uncertain === 1 ? " is" : "s are"} kept as signal. `}
            {decided && "Everything after this step runs again with your new labels. "}
            {waiting ? "The paused processing then continues." : "The decision is used the next time this part of the pipeline runs."}
          </AlertDialog.Description>
          <Flex gap={space.group} justify="end" mt="4">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">
                Go back
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button onClick={() => void finish()}>Save and continue</Button>
            </AlertDialog.Action>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </Flex>
  );
}
