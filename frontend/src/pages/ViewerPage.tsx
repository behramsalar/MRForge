import { Callout, Flex, Heading, SegmentedControl, Select, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useSubjects } from "../api/hooks";
import { ErrorCallout } from "../components/ErrorCallout";
import { Viewer, type ViewerLayout } from "../components/Viewer";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

const NONE = "__none__";

export function ViewerPage({ ws, subject }: { ws: string; subject?: string }) {
  const subjects = useSubjects(ws);
  const label = subject ?? subjects.data?.[0]?.label;
  const images = useQuery({
    queryKey: ["ws", ws, "images", label],
    enabled: !!label,
    queryFn: () =>
      call(
        api.GET("/api/workspaces/{ws_id}/subjects/{label}/images", {
          params: { path: { ws_id: ws, label: label! } },
        }),
      ),
  });
  const [layout, setLayout] = useState<ViewerLayout>("row");
  const [under, setUnder] = useState<string | undefined>();
  const [over, setOver] = useState<string>(NONE);
  const underlays = (images.data ?? []).filter((i) => i.role === "underlay");
  const overlays = (images.data ?? []).filter((i) => i.role === "overlay");
  const underlay = underlays.find((i) => i.relpath === under) ?? underlays[0];
  const overlay = overlays.find((i) => i.relpath === over);

  return (
    <Flex direction="column" gap={space.group}>
      <Heading size={type.pageTitle}>View results</Heading>
      {subjects.data?.length === 0 && (
        <Callout.Root>
          <Callout.Text>
            Nothing to view yet. <a href={href(ws, "import")}>Import scans first.</a>
          </Callout.Text>
        </Callout.Root>
      )}
      {images.error && <ErrorCallout error={(images.error as ApiError).body} />}
      {label && (
        <Flex gap={space.group} align="end" wrap="wrap">
          <Flex direction="column" gap="1">
            <Text size={type.help} weight="medium">
              Subject
            </Text>
            <Select.Root value={label} onValueChange={(v) => (location.hash = href(ws, "view", v))}>
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
          <Flex direction="column" gap="1">
            <Text size={type.help} weight="medium">
              Image
            </Text>
            <Select.Root value={underlay?.relpath} onValueChange={setUnder}>
              <Select.Trigger />
              <Select.Content>
                {underlays.map((i) => (
                  <Select.Item key={i.relpath} value={i.relpath}>
                    {i.name}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </Flex>
          <Flex direction="column" gap="1">
            <Text size={type.help} weight="medium">
              Overlay
            </Text>
            <Select.Root value={overlay?.relpath ?? NONE} onValueChange={setOver} disabled={overlays.length === 0}>
              <Select.Trigger />
              <Select.Content>
                <Select.Item value={NONE}>None</Select.Item>
                {overlays.map((i) => (
                  <Select.Item key={i.relpath} value={i.relpath}>
                    {i.name}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </Flex>
          <SegmentedControl.Root value={layout} onValueChange={(v) => setLayout(v as ViewerLayout)}>
            <SegmentedControl.Item value="row">Three slices</SegmentedControl.Item>
            <SegmentedControl.Item value="grid">With 3D view</SegmentedControl.Item>
          </SegmentedControl.Root>
        </Flex>
      )}
      {label && images.data && overlays.length === 0 && (
        <Text size={type.help} color="gray">
          Overlays appear here after anatomical processing has finished for {label}.
        </Text>
      )}
      {underlay && (
        <Viewer underlay={underlay} overlays={overlay ? [overlay] : []} layout={layout} key={`${underlay.url}|${overlay?.url}`} />
      )}
    </Flex>
  );
}
