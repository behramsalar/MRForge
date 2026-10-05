import { Badge, Callout, Card, Flex, Heading, ScrollArea, Select, Slider, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useSubjects } from "../api/hooks";
import type { IcaComponent } from "../api/types";
import { ErrorCallout } from "../components/ErrorCallout";
import { Viewer } from "../components/Viewer";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { space, type } from "../theme/tokens";

const Z_DEFAULT = 2.3; // REVIEW(domain): the common display threshold for MELODIC z-maps

/**
 * Component review (prototype of the interactive picture): the component's brain map over the
 * mean image in the viewer, with its time course and frequencies below. Labelling comes next.
 */
export function ComponentReviewPage({ ws }: { ws: string }) {
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
  useEffect(() => setNumber(1), [rec?.recording, label]);
  const current: IcaComponent | undefined = rec?.components.find((c) => c.number === number) ?? rec?.components[0];

  // Up and down arrows move through the components.
  useEffect(() => {
    if (!rec) return;
    const on = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
      if (e.key === "ArrowDown") setNumber((n) => Math.min(rec.n_components, n + 1));
      if (e.key === "ArrowUp") setNumber((n) => Math.max(1, n - 1));
    };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  }, [rec]);

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
      </Flex>
      {results.error && <ErrorCallout error={(results.error as ApiError).body} />}
      {results.data && !rec && (
        <EmptyState
          title="No components yet"
          text="Component analysis (MELODIC) has not been run for this subject. It will appear here once it has."
        />
      )}
      {rec && current && (
        <Flex gap={space.group} align="start" wrap="wrap">
          <Card size="2" style={{ flex: "0 0 220px" }}>
            <Heading as="h2" size={type.help} mb="2">
              Components
            </Heading>
            <ScrollArea style={{ maxHeight: "70vh" }}>
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
                      justifyContent: "space-between",
                    }}
                  >
                    <Text size={type.help}>Component {c.number}</Text>
                    <Text size={type.caption} color="gray">
                      {c.variance_pct != null ? `${c.variance_pct.toFixed(1)}%` : ""}
                    </Text>
                  </button>
                ))}
              </Flex>
            </ScrollArea>
            <Text size={type.caption} color="gray" as="p" mt="2">
              Up and down arrows move between components.
            </Text>
          </Card>
          <Flex direction="column" gap={space.group} style={{ flex: "1 1 560px", minWidth: 0 }}>
            <Flex justify="between" align="center" wrap="wrap" gap={space.group}>
              <Heading as="h2" size={type.sectionTitle}>
                Component {current.number} of {rec.n_components}
              </Heading>
              <Flex gap={space.inline} align="center">
                <Badge color="orange" variant="soft">positive</Badge>
                <Badge color="blue" variant="soft">negative</Badge>
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
    </Flex>
  );
}
