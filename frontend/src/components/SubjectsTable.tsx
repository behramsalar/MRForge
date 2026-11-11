import { MagnifyingGlassIcon } from "@radix-ui/react-icons";
import { Badge, Button, Card, Checkbox, Flex, SegmentedControl, Table, Text, TextField } from "@radix-ui/themes";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { Overview } from "../api/types";
import { whenShort } from "../lib/labels";
import "./overview.css";
import { space, type } from "../theme/tokens";
import { DECISION_COLOUR, DECISION_LABEL } from "./QualityDecisionCard";
import { StageChips } from "./StageChips";

type Row = Overview["subjects"][number];
export type Filter = "all" | "todo" | "attention" | "complete" | "excluded";

const PAGE = 20;

const NEEDS_ATTENTION = ["failed", "stopped", "review"];

function attention(r: Row): boolean {
  return r.stages.some((c) => NEEDS_ATTENTION.includes(c.state)) || !!r.motion_flag || r.qc_decision === "review";
}

export const FILTERS: Record<Filter, (r: Row) => boolean> = {
  all: () => true,
  todo: (r) => !r.complete && !attention(r) && r.qc_decision !== "exclude",
  attention: (r) => attention(r) && r.qc_decision !== "exclude",
  complete: (r) => r.complete && r.qc_decision !== "exclude",
  excluded: (r) => r.qc_decision === "exclude",
};

/**
 * Every place that lists subjects uses this table: search, a status filter and paging keep it
 * usable with a hundred subjects. ``onOpen`` makes a row open the subject; ``selected`` with
 * ``onSelect`` makes it a chooser (one subject now, several with ``multi`` in Stage 7).
 */
export function SubjectsTable({
  subjects,
  onOpen,
  selected,
  onSelect,
  multi = false,
  extra,
}: {
  subjects: Row[];
  onOpen?: (label: string) => void;
  selected?: string[];
  onSelect?: (labels: string[]) => void;
  multi?: boolean;
  extra?: (r: Row) => ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(0);
  const shown = useMemo(
    () => subjects.filter((r) => FILTERS[filter](r) && r.label.toLowerCase().includes(query.trim().toLowerCase())),
    [subjects, filter, query],
  );
  useEffect(() => setPage(0), [query, filter]);
  const pages = Math.max(1, Math.ceil(shown.length / PAGE));
  const rows = shown.slice(page * PAGE, page * PAGE + PAGE);
  const counts = useMemo(
    () => ({
      all: subjects.length,
      todo: subjects.filter(FILTERS.todo).length,
      attention: subjects.filter(FILTERS.attention).length,
      complete: subjects.filter(FILTERS.complete).length,
      excluded: subjects.filter(FILTERS.excluded).length,
    }),
    [subjects],
  );
  const chosen = selected ?? [];
  const toggle = (label: string) => {
    if (!onSelect) return;
    if (!multi) onSelect([label]);
    else onSelect(chosen.includes(label) ? chosen.filter((l) => l !== label) : [...chosen, label]);
  };
  const click = (label: string) => (onSelect ? toggle(label) : onOpen?.(label));
  return (
    <Card size="2">
      <Flex direction="column" gap={space.group}>
        <Flex gap={space.group} align="center" wrap="wrap" justify="between">
          <TextField.Root
            placeholder="Search subjects"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ minWidth: 220 }}
            aria-label="Search subjects"
          >
            <TextField.Slot>
              <MagnifyingGlassIcon />
            </TextField.Slot>
          </TextField.Root>
          <SegmentedControl.Root value={filter} onValueChange={(v) => setFilter(v as Filter)}>
            <SegmentedControl.Item value="all">All ({counts.all})</SegmentedControl.Item>
            <SegmentedControl.Item value="todo">To do ({counts.todo})</SegmentedControl.Item>
            <SegmentedControl.Item value="attention">Needs attention ({counts.attention})</SegmentedControl.Item>
            <SegmentedControl.Item value="complete">Complete ({counts.complete})</SegmentedControl.Item>
            {counts.excluded > 0 && <SegmentedControl.Item value="excluded">Excluded ({counts.excluded})</SegmentedControl.Item>}
          </SegmentedControl.Root>
        </Flex>
        <Table.Root size="1" className="st-compact">
          <Table.Header>
            <Table.Row>
              {onSelect && multi && (
                <Table.ColumnHeaderCell style={{ width: 32 }}>
                  <Checkbox
                    aria-label="Select all shown"
                    checked={rows.length > 0 && rows.filter((r) => r.qc_decision !== "exclude").every((r) => chosen.includes(r.label))}
                    onCheckedChange={(on) =>
                      // Excluded subjects are not ticked by "select all" (you can still tick one by hand).
                      onSelect(
                        on === true
                          ? [...new Set([...chosen, ...rows.filter((r) => r.qc_decision !== "exclude").map((r) => r.label)])]
                          : chosen.filter((l) => !rows.some((r) => r.label === l)),
                      )
                    }
                  />
                </Table.ColumnHeaderCell>
              )}
              <Table.ColumnHeaderCell>Subject</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Processing</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Head motion</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Last activity</Table.ColumnHeaderCell>
              {extra && <Table.ColumnHeaderCell />}
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {rows.map((r) => (
              <Table.Row
                key={r.label}
                onClick={() => click(r.label)}
                style={{
                  cursor: onOpen || onSelect ? "pointer" : undefined,
                  background: chosen.includes(r.label) ? "var(--accent-a3)" : undefined,
                  opacity: r.qc_decision === "exclude" ? 0.55 : 1,
                }}
              >
                {onSelect && multi && (
                  <Table.Cell onClick={(e) => e.stopPropagation()}>
                    <Checkbox checked={chosen.includes(r.label)} onCheckedChange={() => toggle(r.label)} aria-label={`Select ${r.label}`} />
                  </Table.Cell>
                )}
                <Table.RowHeaderCell>
                  <Flex align="center" gap="2">
                    <Text weight="medium">{r.label}</Text>
                    {r.complete && (
                      <Badge color="green" variant="soft" size="1">
                        Complete
                      </Badge>
                    )}
                    {r.qc_decision && (
                      <Badge color={DECISION_COLOUR[r.qc_decision as "accept" | "review" | "exclude"]} variant="soft" size="1" title={r.qc_reason ?? undefined}>
                        {DECISION_LABEL[r.qc_decision as "accept" | "review" | "exclude"]}
                      </Badge>
                    )}
                  </Flex>
                </Table.RowHeaderCell>
                <Table.Cell>
                  <StageChips stages={r.stages} />
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
                  {r.last_activity ? (
                    <Text size={type.help} title={r.last_activity_by ?? undefined}>
                      {whenShort(r.last_activity)}
                      {r.last_activity_by ? ` · ${r.last_activity_by}` : ""}
                    </Text>
                  ) : (
                    <Text size={type.help} color="gray">
                      -
                    </Text>
                  )}
                </Table.Cell>
                {extra && <Table.Cell onClick={(e) => e.stopPropagation()}>{extra(r)}</Table.Cell>}
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Root>
        {shown.length === 0 && (
          <Text size={type.help} color="gray">
            No subject matches.
          </Text>
        )}
        {pages > 1 && (
          <Flex justify="between" align="center">
            <Text size={type.help} color="gray">
              {page * PAGE + 1}-{Math.min(shown.length, page * PAGE + PAGE)} of {shown.length}
            </Text>
            <Flex gap="2">
              <Button size="1" variant="soft" color="gray" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Previous
              </Button>
              <Button size="1" variant="soft" color="gray" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
                Next
              </Button>
            </Flex>
          </Flex>
        )}
      </Flex>
    </Card>
  );
}
