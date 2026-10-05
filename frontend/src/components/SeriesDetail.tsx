import { Badge, Callout, Card, Flex, Grid, Heading, Text } from "@radix-ui/themes";
import type { ImportDetail, SeriesRow } from "../api/types";
import { kindName, seconds } from "../lib/labels";
import { space, type } from "../theme/tokens";
import { DecisionDialog, size } from "./SeriesTable";
import { ActionBadge, ConfidenceBadge } from "./ui/Badges";

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <Flex direction="column">
      <Text size={type.caption} color="gray">
        {label}
      </Text>
      <Text size={type.help}>{value}</Text>
    </Flex>
  );
}

/** Everything MRForge knows about one series, and why it decided what it did. */
export function SeriesDetail({ ws, detail, row }: { ws: string; detail: ImportDetail; row: SeriesRow }) {
  const extras = Object.entries(row.entities).map(([k, v]) => `${k} ${v}`);
  return (
    <Card size="3">
      <Flex direction="column" gap={space.group}>
        <Flex justify="between" align="start" gap={space.group}>
          <Flex direction="column" style={{ minWidth: 0 }}>
            <Text size={type.caption} color="gray">
              Series {row.number}
            </Text>
            <Heading as="h2" size={type.sectionTitle} style={{ wordBreak: "break-word" }}>
              {row.label}
            </Heading>
          </Flex>
          <DecisionDialog ws={ws} detail={detail} row={row} key={`${row.uid}-${row.action}-${row.kind}`} />
        </Flex>

        <Flex gap={space.inline} wrap="wrap">
          <ActionBadge action={row.action} />
          <ConfidenceBadge level={row.confidence} />
          {row.decided_by === "user" && (
            <Badge variant="outline" color="gray">
              your choice
            </Badge>
          )}
          {row.organized && (
            <Badge color="green" variant="solid">
              Imported
            </Badge>
          )}
        </Flex>

        <Flex direction="column">
          <Text size={type.caption} color="gray">
            Detected as
          </Text>
          <Text size={type.body}>
            {kindName(row.kind)}
            {extras.length ? ` (${extras.join(", ")})` : ""}
          </Text>
        </Flex>

        {row.needs.length > 0 && (
          <Callout.Root color="amber" size="1">
            <Callout.Text>
              Needs your input: {row.needs.map((n) => (n === "task" ? "a task name" : n)).join(", ")}.
            </Callout.Text>
          </Callout.Root>
        )}

        {row.reasons.length > 0 && (
          <Flex direction="column" gap="1">
            <Text size={type.caption} color="gray">
              Why MRForge thinks this
            </Text>
            {row.reasons.map((r) => (
              <Text key={r} size={type.help}>
                {r}
              </Text>
            ))}
          </Flex>
        )}

        <Grid columns="2" gap={space.inline}>
          <Fact label="Image size" value={size(row)} />
          <Fact label="Files" value={String(row.n_files)} />
          <Fact label="Repetition time" value={seconds(row.repetition_time_s)} />
          <Fact label="Echo time" value={row.echo_time_s ? `${Math.round(row.echo_time_s * 1000 * 10) / 10} ms` : "-"} />
        </Grid>

        {row.warnings.length > 0 && (
          <Callout.Root color="gray" size="1">
            <Callout.Text>{row.warnings.join(" ")}</Callout.Text>
          </Callout.Root>
        )}
      </Flex>
    </Card>
  );
}
