import { CopyIcon } from "@radix-ui/react-icons";
import { Badge, Button, Callout, Card, Code, Flex, Heading, Select, Table, Text } from "@radix-ui/themes";
import { useState } from "react";
import { useSubjects } from "../api/hooks";
import { whenShort } from "../lib/labels";
import { space, type } from "../theme/tokens";
import { useSubjectReport } from "./QualityGrid";

function CopyCommand({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      size="1"
      variant="ghost"
      color="gray"
      aria-label="Copy command"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          /* clipboard not available: nothing to do */
        }
      }}
    >
      <CopyIcon /> {done ? "Copied" : ""}
    </Button>
  );
}

/** What was done to one subject, step by step, from the recorded runs: tools, versions, when, by
 * whom and the exact commands. The methods text will be generated from the same records; its
 * place is reserved on top. */
export function ProvenanceView({ ws }: { ws: string }) {
  const subjects = useSubjects(ws);
  const [chosen, setChosen] = useState<string | undefined>();
  const label = chosen ?? subjects.data?.[0]?.label ?? "";
  const report = useSubjectReport(ws, label, !!label);
  const runs = (report.data?.sections ?? []).flatMap((s) => s.runs);
  return (
    <Flex direction="column" gap={space.section}>
      <Card size="3">
        <Flex direction="column" gap={space.inline}>
          <Flex gap={space.group} align="center">
            <Heading as="h2" size={type.sectionTitle}>
              Methods text
            </Heading>
            <Badge color="gray" variant="soft">
              Coming later
            </Badge>
          </Flex>
          <Text size={type.help} color="gray">
            A methods paragraph for your paper will be assembled here from the records below, never written freehand.
            Until then, the table lists exactly what was done, with tools, versions and commands.
          </Text>
        </Flex>
      </Card>

      <Card size="3">
        <Flex direction="column" gap={space.group}>
          <Flex gap={space.group} align="center" justify="between" wrap="wrap">
            <Heading as="h2" size={type.sectionTitle}>
              What was done to a subject
            </Heading>
            {(subjects.data ?? []).length > 0 && (
              <Select.Root value={label} onValueChange={setChosen}>
                <Select.Trigger aria-label="Subject" />
                <Select.Content>
                  {(subjects.data ?? []).map((s) => (
                    <Select.Item key={s.label} value={s.label}>
                      {s.label}
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
            )}
          </Flex>
          {subjects.data && subjects.data.length === 0 && (
            <Text size={type.help} color="gray">
              No subjects yet. Import data and process it; every step is recorded here.
            </Text>
          )}
          {report.isError && (
            <Callout.Root color="red" size="1">
              <Callout.Text>The record of {label} could not be read.</Callout.Text>
            </Callout.Root>
          )}
          {label && report.data && runs.length === 0 && (
            <Text size={type.help} color="gray">
              Nothing has been processed for {label} yet.
            </Text>
          )}
          {runs.length > 0 && (
            <Table.Root size="1" className="st-compact">
              <Table.Header>
                <Table.Row>
                  <Table.ColumnHeaderCell>Step</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>When</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>By</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>Tool versions</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>Command</Table.ColumnHeaderCell>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {runs.map((r) => {
                  const cmd = r.commands[0]?.command;
                  return (
                    <Table.Row key={`${r.job_id}-${r.step}-${r.recording}`}>
                      <Table.RowHeaderCell>
                        {r.title}
                        {r.recording ? <Text size={type.caption} color="gray"> · {r.recording}</Text> : null}
                      </Table.RowHeaderCell>
                      <Table.Cell>{whenShort(r.finished ?? r.started)}</Table.Cell>
                      <Table.Cell>{r.started_by ?? ""}</Table.Cell>
                      <Table.Cell>
                        <Text size={type.caption}>
                          {Object.entries(r.tool_versions).map(([k, v]) => `${k} ${v}`).join("; ")}
                        </Text>
                      </Table.Cell>
                      <Table.Cell style={{ maxWidth: 360 }}>
                        {cmd ? (
                          <Flex gap="2" align="center">
                            <Code size="1" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }} title={cmd}>
                              {cmd}
                            </Code>
                            <CopyCommand text={cmd} />
                          </Flex>
                        ) : (
                          <Text size={type.caption} color="gray">none recorded</Text>
                        )}
                      </Table.Cell>
                    </Table.Row>
                  );
                })}
              </Table.Body>
            </Table.Root>
          )}
          <Text size={type.caption} color="gray">
            Every step also keeps its full record (parameters, input and output file hashes, logs) in Jobs and in the
            subject's report.
          </Text>
        </Flex>
      </Card>
    </Flex>
  );
}
