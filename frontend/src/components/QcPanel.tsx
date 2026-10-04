import { Badge, Card, Flex, Grid, Heading, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { helpFor } from "../lib/qcHelp";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

/** Quality-check results of a subject's finished functional steps: numbers and pictures. */
export function QcPanel({ ws, subject }: { ws: string; subject: string }) {
  const qc = useQuery({
    queryKey: ["ws", ws, "qc", subject],
    queryFn: () =>
      call(
        api.GET("/api/workspaces/{ws_id}/subjects/{label}/qc", {
          params: { path: { ws_id: ws, label: subject } },
        }),
      ),
  });
  if (qc.error) return <ErrorCallout error={(qc.error as ApiError).body} />;
  const groups = qc.data ?? [];
  if (groups.length === 0) return null;
  return (
    <Flex direction="column" gap={space.group}>
      <Heading size={type.sectionTitle}>Quality checks</Heading>
      <Text size={type.help} color="gray">
        These are signs to look at, not verdicts. MRForge never excludes data by itself.
      </Text>
      {groups.map((g) => (
        <Card key={`${g.step}/${g.run}`}>
          <Flex direction="column" gap={space.group}>
            <Flex align="center" gap={space.inline}>
              <Text weight="bold" size={type.body}>
                {g.title}
              </Text>
              {g.run && (
                <Badge variant="soft" color="gray">
                  {g.run}
                </Badge>
              )}
            </Flex>
            <Grid columns={{ initial: "1", sm: "2" }} gap={space.inline}>
              {g.items
                .filter((i) => i.kind === "metric")
                .map((i) => (
                  <Flex key={i.name} justify="between" gap={space.group}>
                    <Text size={type.help} color="gray">
                      {i.name}
                    </Text>
                    <Text size={type.help} weight="medium">
                      {i.value}
                    </Text>
                  </Flex>
                ))}
            </Grid>
            {g.items
              .filter((i) => i.kind !== "metric" && i.image_url)
              .map((i) => (
                <Flex key={i.name} direction="column" gap="1">
                  <Text size={type.help} weight="medium">
                    {i.name}
                  </Text>
                  <a href={i.image_url!} target="_blank" rel="noreferrer">
                    <img
                      src={i.image_url!}
                      alt={i.name}
                      style={{ width: "100%", borderRadius: "var(--radius-3)", background: "black" }}
                    />
                  </a>
                  {helpFor(i.name) && (
                    <Text size={type.caption} color="gray">
                      {helpFor(i.name)}
                    </Text>
                  )}
                </Flex>
              ))}
          </Flex>
        </Card>
      ))}
    </Flex>
  );
}
