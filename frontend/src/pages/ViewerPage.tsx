import { Cross2Icon, EyeOpenIcon, LayersIcon } from "@radix-ui/react-icons";
import { Badge, Callout, Card, Flex, IconButton, ScrollArea, SegmentedControl, Select, Slider, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useSubjects } from "../api/hooks";
import type { ViewerImageInfo } from "../api/types";
import { ErrorCallout } from "../components/ErrorCallout";
import { Viewer, type ViewerLayout } from "../components/Viewer";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { humanSize } from "../lib/labels";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

const COLORMAPS = ["gray", "red", "green", "blue", "winter", "hot", "viridis"];
const LARGE = 150_000_000; // bytes: warn that loading takes a while

type Overlay = { relpath: string; opacity: number; colormap: string };

function groups(images: ViewerImageInfo[]): [string, ViewerImageInfo[]][] {
  const out = new Map<string, ViewerImageInfo[]>();
  for (const i of images) out.set(i.group, [...(out.get(i.group) ?? []), i]);
  return [...out.entries()];
}

/** Pick any image of a subject, raw or processed, add overlays, and look at it. */
export function ViewerPage({ ws, subject, image }: { ws: string; subject?: string; image?: string }) {
  const subjects = useSubjects(ws);
  const label = subject ?? subjects.data?.[0]?.label;
  const list = useQuery({
    queryKey: ["ws", ws, "images", label],
    enabled: !!label,
    queryFn: () =>
      call(
        api.GET("/api/workspaces/{ws_id}/subjects/{label}/images", {
          params: { path: { ws_id: ws, label: label! } },
        }),
      ),
  });
  const images = list.data ?? [];
  const [underPath, setUnderPath] = useState<string | undefined>();
  const [overlays, setOverlays] = useState<Overlay[]>([]);
  const [layout, setLayout] = useState<ViewerLayout>("row");
  const [frame, setFrame] = useState(0);
  const [frames, setFrames] = useState(1);
  const [failed, setFailed] = useState<string | null>(null);

  // First image: the one asked for in the address, else a sensible default.
  useEffect(() => {
    if (!images.length) return;
    const wanted = image ? images.find((i) => i.relpath === image) : undefined;
    const fallback =
      images.find((i) => i.name === "T1, bias-corrected") ??
      images.find((i) => i.name === "T1 (original)") ??
      images.find((i) => i.role === "underlay") ??
      images[0];
    setUnderPath((wanted ?? fallback).relpath);
    setOverlays([]);
    setFrame(0);
    setFailed(null);
  }, [list.data, image]); // eslint-disable-line react-hooks/exhaustive-deps

  const under = images.find((i) => i.relpath === underPath);
  const overlayInfo = useMemo(
    () => overlays.map((o) => ({ o, info: images.find((i) => i.relpath === o.relpath) })).filter((x) => x.info),
    [overlays, images],
  );
  const pick = (i: ViewerImageInfo) => {
    setUnderPath(i.relpath);
    setOverlays((cur) => cur.filter((o) => o.relpath !== i.relpath));
    setFrame(0);
    setFrames(1);
    setFailed(null);
  };
  const toggleOverlay = (i: ViewerImageInfo) => {
    if (i.relpath === underPath) return;
    setOverlays((cur) =>
      cur.some((o) => o.relpath === i.relpath)
        ? cur.filter((o) => o.relpath !== i.relpath)
        : [...cur, { relpath: i.relpath, opacity: 0.5, colormap: i.colormap ?? "red" }],
    );
  };
  const update = (relpath: string, change: Partial<Overlay>) =>
    setOverlays((cur) => cur.map((o) => (o.relpath === relpath ? { ...o, ...change } : o)));

  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader title="Viewer" description="Look at any image of a subject, raw or processed, with overlays." />
      {subjects.data?.length === 0 && (
        <EmptyState title="Nothing to view yet" text="Images appear here once you have imported scans." action="Import scans" href={href(ws, "data")} />
      )}
      {list.error && <ErrorCallout error={(list.error as ApiError).body} />}
      {label && (
        <Flex gap={space.group} align="start" wrap="wrap">
          <Card size="2" style={{ flex: "0 0 340px", maxWidth: "100%" }}>
            <Flex direction="column" gap={space.group}>
              <Flex direction="column" gap="1">
                <Text size={type.help} weight="medium">
                  Subject
                </Text>
                <Select.Root value={label} onValueChange={(v) => (location.hash = href(ws, "viewer", v))}>
                  <Select.Trigger />
                  <Select.Content>
                    {(subjects.data ?? []).map((s) => (
                      <Select.Item key={s.label} value={s.label}>
                        {s.label}
                      </Select.Item>
                    ))}
                  </Select.Content>
                </Select.Root>
              </Flex>
              <Text size={type.caption} color="gray">
                Click an image to show it. Use the layers button to lay another image over it.
              </Text>
              <ScrollArea style={{ maxHeight: "52vh" }}>
                <Flex direction="column" gap={space.group}>
                  {groups(images).map(([group, items]) => (
                    <Flex key={group} direction="column" gap="1">
                      <Text size={type.caption} weight="bold" color="gray" style={{ textTransform: "uppercase" }}>
                        {group}
                      </Text>
                      {items.map((i) => {
                        const shown = i.relpath === underPath;
                        const layered = overlays.some((o) => o.relpath === i.relpath);
                        return (
                          <Flex
                            key={i.relpath}
                            align="center"
                            gap="1"
                            style={{
                              padding: "var(--space-1) var(--space-2)",
                              borderRadius: "var(--radius-2)",
                              background: shown ? "var(--accent-a4)" : layered ? "var(--gray-a3)" : undefined,
                            }}
                          >
                            <button
                              onClick={() => pick(i)}
                              style={{ all: "unset", cursor: "pointer", flex: 1, minWidth: 0, fontSize: "var(--font-size-2)" }}
                            >
                              {i.name}
                              {i.volumes ? (
                                <Text size={type.caption} color="gray">
                                  {" "}
                                  · {i.volumes} volumes
                                </Text>
                              ) : null}
                            </button>
                            <IconButton
                              size="1"
                              variant={layered ? "solid" : "ghost"}
                              color={layered ? undefined : "gray"}
                              disabled={shown}
                              aria-label={layered ? "Remove overlay" : "Add as overlay"}
                              onClick={() => toggleOverlay(i)}
                            >
                              <LayersIcon />
                            </IconButton>
                          </Flex>
                        );
                      })}
                    </Flex>
                  ))}
                  {list.data && images.length === 0 && (
                    <Text size={type.help} color="gray">
                      This subject has no images yet.
                    </Text>
                  )}
                </Flex>
              </ScrollArea>
            </Flex>
          </Card>

          <Flex direction="column" gap={space.group} style={{ flex: "1 1 560px", minWidth: 0 }}>
            {under && (
              <Flex justify="between" align="center" gap={space.group} wrap="wrap">
                <Flex align="center" gap={space.inline}>
                  <EyeOpenIcon />
                  <Text weight="bold">{under.name}</Text>
                  {under.size_bytes > LARGE && (
                    <Badge color="amber" variant="soft">
                      Large image ({humanSize(under.size_bytes)}): loading takes a moment
                    </Badge>
                  )}
                </Flex>
                <SegmentedControl.Root value={layout} onValueChange={(v) => setLayout(v as ViewerLayout)}>
                  <SegmentedControl.Item value="row">Three slices</SegmentedControl.Item>
                  <SegmentedControl.Item value="grid">With 3D view</SegmentedControl.Item>
                </SegmentedControl.Root>
              </Flex>
            )}
            {failed && (
              <Callout.Root color="red">
                <Callout.Text>
                  {failed} The file may be damaged or very large. Try another image, or run the step that makes it again.
                </Callout.Text>
              </Callout.Root>
            )}
            {frames > 1 && (
              <Flex align="center" gap={space.group}>
                <Text size={type.help} style={{ whiteSpace: "nowrap" }}>
                  Volume {frame + 1} of {frames}
                </Text>
                <Slider min={0} max={frames - 1} step={1} value={[frame]} onValueChange={(v) => setFrame(v[0])} />
              </Flex>
            )}
            {under && (
              <Viewer
                key={under.url}
                underlay={under.url}
                overlays={overlayInfo.map(({ o, info }) => ({ url: info!.url, colormap: o.colormap, opacity: o.opacity }))}
                layout={layout}
                frame={frame}
                height="62vh"
                onLoaded={setFrames}
                onError={setFailed}
              />
            )}
            {overlayInfo.length > 0 && (
              <Card size="2">
                <Flex direction="column" gap={space.group}>
                  <Text size={type.help} weight="medium">
                    Overlays
                  </Text>
                  {overlayInfo.map(({ o, info }) => (
                    <Flex key={o.relpath} align="center" gap={space.group} wrap="wrap">
                      <Text size={type.help} style={{ flex: "1 1 200px", minWidth: 0 }}>
                        {info!.name}
                      </Text>
                      <Flex align="center" gap={space.inline} style={{ flex: "1 1 160px" }}>
                        <Text size={type.caption} color="gray">
                          Opacity
                        </Text>
                        <Slider
                          min={0}
                          max={100}
                          value={[Math.round(o.opacity * 100)]}
                          onValueChange={(v) => update(o.relpath, { opacity: v[0] / 100 })}
                        />
                      </Flex>
                      <Select.Root value={o.colormap} onValueChange={(v) => update(o.relpath, { colormap: v })}>
                        <Select.Trigger />
                        <Select.Content>
                          {COLORMAPS.map((c) => (
                            <Select.Item key={c} value={c}>
                              {c}
                            </Select.Item>
                          ))}
                        </Select.Content>
                      </Select.Root>
                      <IconButton size="1" variant="ghost" color="gray" aria-label="Remove overlay" onClick={() => toggleOverlay(info!)}>
                        <Cross2Icon />
                      </IconButton>
                    </Flex>
                  ))}
                </Flex>
              </Card>
            )}
          </Flex>
        </Flex>
      )}
    </Flex>
  );
}
