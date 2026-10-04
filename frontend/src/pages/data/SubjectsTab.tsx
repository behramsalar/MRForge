import { Badge, Button, Card, Flex, Heading, Table, Text } from "@radix-ui/themes";
import { useState } from "react";
import { useSubjectData, useSubjects } from "../../api/hooks";
import { EmptyState } from "../../components/ui/Layout";
import { datatypeLabel, describeShape, humanSize, seconds } from "../../lib/labels";
import { href } from "../../lib/router";
import { space, type } from "../../theme/tokens";

/** The raw images of each subject: what each file is, its size, and a way to look at it. */
export function SubjectsTab({ ws }: { ws: string }) {
  const subjects = useSubjects(ws);
  const [chosen, setChosen] = useState<string | undefined>();
  const label = chosen ?? subjects.data?.[0]?.label;
  const data = useSubjectData(ws, label);
  if (subjects.data && subjects.data.length === 0) {
    return (
      <EmptyState
        title="No subjects yet"
        text="Subjects appear here once you have imported scans."
        action="Go to imports"
        href={href(ws, "data", "")}
      />
    );
  }
  return (
    <Flex gap={space.group} align="start" wrap="wrap">
      <Flex direction="column" gap="2" style={{ flex: "0 0 220px" }}>
        {(subjects.data ?? []).map((s) => (
          <Button
            key={s.label}
            variant={s.label === label ? "solid" : "soft"}
            color={s.label === label ? undefined : "gray"}
            style={{ justifyContent: "space-between" }}
            onClick={() => setChosen(s.label)}
          >
            {s.label}
            <Badge variant="soft" color="gray">
              {s.files.length}
            </Badge>
          </Button>
        ))}
      </Flex>
      <Card size="3" style={{ flex: "1 1 520px", minWidth: 0 }}>
        <Flex direction="column" gap={space.group}>
          <Flex justify="between" align="center" gap={space.group} wrap="wrap">
            <Heading size={type.sectionTitle}>{label}</Heading>
            {data.data && (
              <Text size={type.help} color="gray">
                {data.data.files.length} images · {humanSize(data.data.bytes_total)}
              </Text>
            )}
          </Flex>
          <Table.Root>
            <Table.Header>
              <Table.Row>
                <Table.ColumnHeaderCell>Type</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Recording</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Image size</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Repetition time</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>File size</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell />
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {(data.data?.files ?? []).map((f) => (
                <Table.Row key={f.relpath}>
                  <Table.RowHeaderCell>
                    <Flex direction="column">
                      <Text size={type.help}>{datatypeLabel[f.datatype] ?? f.datatype}</Text>
                      <Text size={type.caption} color="gray">
                        {f.suffix}
                      </Text>
                    </Flex>
                  </Table.RowHeaderCell>
                  <Table.Cell>{f.recording || "-"}</Table.Cell>
                  <Table.Cell>{describeShape(f.shape)}</Table.Cell>
                  <Table.Cell>{seconds(f.repetition_time_s)}</Table.Cell>
                  <Table.Cell>{humanSize(f.size_bytes)}</Table.Cell>
                  <Table.Cell>
                    <Button asChild size="1" variant="soft" color="gray">
                      <a href={href(ws, "viewer", label)}>View</a>
                    </Button>
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table.Root>
          {data.data && data.data.files.length === 0 && (
            <Text size={type.help} color="gray">
              No images imported for this subject yet.
            </Text>
          )}
        </Flex>
      </Card>
    </Flex>
  );
}
