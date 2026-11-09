import { Badge, Card, Flex, Heading, Select, SegmentedControl, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { boundaries, cellColor, histogram, meanOffDiagonal, type Stat } from "../lib/matrix";
import { matrixScale, space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

const SIZE = 560; // drawing size in CSS pixels

type Hover = { i: number; j: number } | null;

/** Looks at one participant's matrix: the same numbers as the .txt files, drawn on a fixed
 * colour scale, with the names of the regions on hover. Only reads; nothing is recomputed. */
export function ConnectivityMatrixView({ ws }: { ws: string }) {
  const results = useQuery({
    queryKey: ["ws", ws, "roi-results"],
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/roi-results", { params: { path: { ws_id: ws } } })),
  });
  const rows = results.data ?? [];
  const [chosen, setChosen] = useState("");
  const [stat, setStat] = useState<Stat>("r");
  const key = (r: (typeof rows)[number]) => JSON.stringify([r.subject, r.session, r.recording, r.atlas]);
  const current = rows.find((r) => key(r) === chosen) ?? rows[0];
  const matrix = useQuery({
    queryKey: ["ws", ws, "roi-matrix", current ? key(current) : ""],
    enabled: !!current,
    queryFn: () =>
      call(
        api.GET("/api/workspaces/{ws_id}/roi-matrix", {
          params: {
            path: { ws_id: ws },
            query: {
              subject: current!.subject,
              atlas: current!.atlas,
              recording: current!.recording,
              ...(current!.session ? { session: current!.session } : {}),
            },
          },
        }),
      ),
  });
  const data = matrix.data;
  const values = data ? (stat === "r" ? data.r : data.z) : [];
  const n = data?.regions.length ?? 0;
  const canvas = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<Hover>(null);
  const groups = useMemo(() => data?.regions.map((r) => `${r.hemisphere}|${r.network}`) ?? [], [data]);

  useEffect(() => {
    const el = canvas.current;
    if (!el || !data || n === 0) return;
    const ratio = window.devicePixelRatio || 1;
    el.width = SIZE * ratio;
    el.height = SIZE * ratio;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const cell = SIZE / n;
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const [r, g, b] = cellColor(values[i][j], stat, i === j);
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.fillRect(j * cell, i * cell, Math.ceil(cell), Math.ceil(cell));
      }
    }
    // Regions with little or no signal: hatched rows and columns.
    ctx.strokeStyle = matrixScale.flag;
    ctx.lineWidth = 1;
    data.regions.forEach((region, k) => {
      if (!region.low_coverage && !region.empty) return;
      for (const [x, y, w, h] of [
        [0, k * cell, SIZE, cell],
        [k * cell, 0, cell, SIZE],
      ]) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(x, y, w, h);
        ctx.clip();
        ctx.beginPath();
        for (let d = -SIZE; d < SIZE * 2; d += 6) {
          ctx.moveTo(d, 0);
          ctx.lineTo(d + SIZE, SIZE);
        }
        ctx.stroke();
        ctx.restore();
      }
    });
    ctx.strokeStyle = matrixScale.boundary;
    for (const k of boundaries(groups)) {
      ctx.beginPath();
      ctx.moveTo(k * cell, 0);
      ctx.lineTo(k * cell, SIZE);
      ctx.moveTo(0, k * cell);
      ctx.lineTo(SIZE, k * cell);
      ctx.stroke();
    }
    if (hover) {
      ctx.strokeStyle = "#000";
      ctx.lineWidth = 2;
      ctx.strokeRect(hover.j * cell, hover.i * cell, cell, cell);
    }
  }, [data, values, stat, n, groups, hover]);

  const onMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (n === 0) return;
    const box = e.currentTarget.getBoundingClientRect();
    const i = Math.floor(((e.clientY - box.top) / box.height) * n);
    const j = Math.floor(((e.clientX - box.left) / box.width) * n);
    setHover(i >= 0 && j >= 0 && i < n && j < n ? { i, j } : null);
  };

  const hist = useMemo(() => (data ? histogram(values, stat) : null), [data, values, stat]);
  const mean = data ? meanOffDiagonal(values) : null;
  const peak = hist ? Math.max(1, ...hist.counts) : 1;
  const a = hover && data ? data.regions[hover.i] : null;
  const b = hover && data ? data.regions[hover.j] : null;
  const hoverValue = hover && data ? values[hover.i][hover.j] : null;

  if (results.error) return <ErrorCallout error={(results.error as ApiError).body} />;
  return (
    <Card size="3">
      <Flex direction="column" gap={space.group}>
        <Flex justify="between" align="center" wrap="wrap" gap={space.group}>
          <Heading as="h2" size={type.sectionTitle}>
            Matrix view
          </Heading>
          <Flex gap={space.group} align="center" wrap="wrap">
            {rows.length > 0 && (
              <Select.Root value={current ? key(current) : ""} onValueChange={setChosen}>
                <Select.Trigger aria-label="Result to look at" />
                <Select.Content>
                  {rows.map((r) => (
                    <Select.Item key={key(r)} value={key(r)}>
                      {r.subject}
                      {r.session ? ` ${r.session}` : ""} {r.recording} · {r.atlas_name}
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
            )}
            <SegmentedControl.Root value={stat} onValueChange={(v) => setStat(v as Stat)}>
              <SegmentedControl.Item value="r">Pearson r</SegmentedControl.Item>
              <SegmentedControl.Item value="z">Fisher z</SegmentedControl.Item>
            </SegmentedControl.Root>
          </Flex>
        </Flex>
        {rows.length === 0 && (
          <Text size={type.help} color="gray">
            No matrix yet. Run the Connectivity stage for a subject and the matrix appears here.
          </Text>
        )}
        {matrix.error && <ErrorCallout error={(matrix.error as ApiError).body} />}
        {data && (
          <Flex gap={space.section} wrap="wrap" align="start">
            <canvas
              ref={canvas}
              role="img"
              aria-label={`Correlation matrix of ${n} regions`}
              style={{ width: SIZE, height: SIZE, maxWidth: "100%", cursor: "crosshair" }}
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
            />
            <Flex direction="column" gap={space.group} style={{ minWidth: 260, flex: 1 }}>
              <Text size={type.help} style={{ minHeight: 64 }}>
                {a && b ? (
                  <>
                    <b>{a.name}</b> × <b>{b.name}</b>
                    <br />
                    {hover!.i === hover!.j
                      ? "diagonal (a region with itself)"
                      : hoverValue === null
                        ? "no value: a region has no usable signal"
                        : `${stat === "r" ? "r" : "z"} = ${hoverValue.toFixed(3)}`}
                    {(a.network || b.network) && (
                      <>
                        <br />
                        {a.network || "no network"} / {b.network || "no network"}
                      </>
                    )}
                    <br />
                    Signal coverage: {a.coverage === null ? "?" : `${Math.round(a.coverage * 100)}%`} /{" "}
                    {b.coverage === null ? "?" : `${Math.round(b.coverage * 100)}%`}
                  </>
                ) : (
                  <span style={{ color: "var(--gray-11)" }}>Point at a cell to see the two regions and the value.</span>
                )}
              </Text>
              <Flex align="center" gap="2">
                <div
                  aria-hidden
                  style={{
                    width: 160,
                    height: 12,
                    borderRadius: 4,
                    background: `linear-gradient(to right, rgb(${matrixScale.negative}), rgb(${matrixScale.zero}), rgb(${matrixScale.positive}))`,
                  }}
                />
                <Text size={type.caption} color="gray">
                  {-matrixScale.range[stat]} to {matrixScale.range[stat]}
                </Text>
              </Flex>
              {hist && (
                <svg viewBox="0 0 300 80" width="300" role="img" aria-label="Distribution of the values between regions">
                  {hist.counts.map((c, k) => (
                    <rect
                      key={k}
                      x={k * 10}
                      y={70 - (c / peak) * 66}
                      width={9}
                      height={(c / peak) * 66}
                      fill="var(--gray-9)"
                    />
                  ))}
                  <line x1="150" y1="0" x2="150" y2="70" stroke="var(--gray-8)" strokeDasharray="3 3" />
                  <text x="0" y="79" fontSize="9" fill="var(--gray-11)">
                    {hist.low}
                  </text>
                  <text x="150" y="79" fontSize="9" fill="var(--gray-11)" textAnchor="middle">
                    0
                  </text>
                  <text x="300" y="79" fontSize="9" fill="var(--gray-11)" textAnchor="end">
                    {hist.high}
                  </text>
                </svg>
              )}
              <Text size={type.caption} color="gray">
                {n} regions, {current?.volumes} volumes. Mean between regions:{" "}
                {mean === null ? "none" : mean.toFixed(3)}. The diagonal is drawn grey. Hatched rows and columns are regions
                with little or no signal.
              </Text>
              {data.flags.map((f) => (
                <Badge key={f} color="amber" variant="soft" style={{ whiteSpace: "normal" }}>
                  {f}
                </Badge>
              ))}
            </Flex>
          </Flex>
        )}
      </Flex>
    </Card>
  );
}
