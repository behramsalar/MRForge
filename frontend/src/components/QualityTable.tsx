import { Badge, Button, Card, Flex, SegmentedControl, Table, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import type { Overview } from "../api/types";
import { href } from "../lib/router";
import { reviewable } from "../lib/overviewSummary";
import { space, stageColor, stageLabel, type } from "../theme/tokens";
import { DECISION_COLOUR, DECISION_LABEL } from "./QualityDecisionCard";

type Row = Overview["subjects"][number];
type Show = "todo" | "flagged" | "all";

const FILTER: Record<Show, (r: Row) => boolean> = {
  todo: (r) => reviewable(r) && !r.qc_decision,
  flagged: (r) => !!r.motion_flag || r.qc_decision === "review" || r.stages.some((c) => c.state === "failed" || c.state === "review"),
  all: () => true,
};

/** Every subject with what the checks found and the decision so far. The pictures and numbers are
 * in each subject's report; the decision is made on the subject page. Nothing here excludes anyone. */
export function QualityTable({ ws, subjects }: { ws: string; subjects: Row[] }) {
  const [show, setShow] = useState<Show>("todo");
  const shown = useMemo(() => subjects.filter(FILTER[show]), [subjects, show]);
  const count = (s: Show) => subjects.filter(FILTER[s]).length;
  const state = (r: Row, id: string) => r.stages.find((c) => c.id === id)?.state ?? "none";
  return (
    <Card size="2">
      <Flex direction="column" gap={space.group}>
        <SegmentedControl.Root size="1" value={show} onValueChange={(v) => setShow(v as Show)} style={{ alignSelf: "flex-start" }}>
          <SegmentedControl.Item value="todo">Needs a decision {count("todo")}</SegmentedControl.Item>
          <SegmentedControl.Item value="flagged">Flagged {count("flagged")}</SegmentedControl.Item>
          <SegmentedControl.Item value="all">All {count("all")}</SegmentedControl.Item>
        </SegmentedControl.Root>
        <Table.Root size="1" className="st-compact">
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeaderCell>Subject</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Functional</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Head motion</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Artifact rejection</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Decision</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell />
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {shown.map((r) => {
              const pre = state(r, "preprocessing");
              const ica = state(r, "artifact_rejection");
              return (
                <Table.Row key={r.label} style={{ opacity: r.qc_decision === "exclude" ? 0.55 : 1 }}>
                  <Table.RowHeaderCell>
                    <a href={href(ws, "subject", r.label)}>{r.label}</a>
                  </Table.RowHeaderCell>
                  <Table.Cell>
                    <Badge color={stageColor[pre] ?? "gray"} variant="soft" size="1">
                      {stageLabel[pre] ?? pre}
                    </Badge>
                  </Table.Cell>
                  <Table.Cell>
                    {r.qc ? (
                      <Text size={type.help} title={`${r.qc.volumes_above} of ${r.qc.n_volumes} volumes above ${r.qc.threshold_mm} mm`}>
                        FD {r.qc.fd_mean_mm} mm
                        {r.motion_flag && (
                          <Text size={type.caption} color="amber">
                            {" "}
                            · check
                          </Text>
                        )}
                      </Text>
                    ) : (
                      <Text size={type.help} color="gray">
                        -
                      </Text>
                    )}
                  </Table.Cell>
                  <Table.Cell>
                    {ica === "none" || ica === "unavailable" ? (
                      <Text size={type.help} color="gray">
                        -
                      </Text>
                    ) : (
                      <Badge color={stageColor[ica] ?? "gray"} variant="soft" size="1">
                        {stageLabel[ica] ?? ica}
                      </Badge>
                    )}
                  </Table.Cell>
                  <Table.Cell>
                    {r.qc_decision ? (
                      <Badge color={DECISION_COLOUR[r.qc_decision as "accept" | "review" | "exclude"]} variant="soft" size="1" title={r.qc_reason ?? undefined}>
                        {DECISION_LABEL[r.qc_decision as "accept" | "review" | "exclude"]}
                      </Badge>
                    ) : (
                      <Text size={type.help} color="gray">
                        {reviewable(r) ? "Not decided" : "-"}
                      </Text>
                    )}
                  </Table.Cell>
                  <Table.Cell>
                    <Flex gap="2" justify="end">
                      <Button size="1" variant="soft" color="gray" asChild>
                        <a href={href(ws, "subject", r.label, "results")}>Report</a>
                      </Button>
                      <Button size="1" variant="soft" asChild>
                        <a href={href(ws, "subject", r.label)}>Decide</a>
                      </Button>
                    </Flex>
                  </Table.Cell>
                </Table.Row>
              );
            })}
          </Table.Body>
        </Table.Root>
        {shown.length === 0 && (
          <Text size={type.help} color="gray">
            {show === "todo" ? "Nobody is waiting for a decision." : "No subject matches."}
          </Text>
        )}
      </Flex>
    </Card>
  );
}
