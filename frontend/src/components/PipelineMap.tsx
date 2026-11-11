import { CheckIcon, Cross2Icon, ExclamationTriangleIcon, MagnifyingGlassIcon, PersonIcon, UpdateIcon } from "@radix-ui/react-icons";
import { Badge, Card, Flex, Heading, SegmentedControl, Text, TextField, Tooltip } from "@radix-ui/themes";
import { useMemo, useState, type ReactNode } from "react";
import type { Overview } from "../api/types";
import { when } from "../lib/labels";
import { reviewable } from "../lib/overviewSummary";
import { space, stageLabel, type } from "../theme/tokens";
import { FILTERS, type Filter } from "./SubjectsTable";
import { DECISION_COLOUR, DECISION_LABEL } from "./QualityDecisionCard";
import "./overview.css";

type Row = Overview["subjects"][number];

const COLUMNS: [string, string][] = [
  ["import", "Import"],
  ["anatomical", "Anatomy"],
  ["preprocessing", "Functional"],
  ["artifact_rejection", "Clean-up"],
  ["standard_space", "Standard"],
  ["connectivity", "Connect."],
  ["diffusion", "Diffusion"],
];

const ICON: Record<string, ReactNode> = {
  done: <CheckIcon />,
  failed: <Cross2Icon />,
  stopped: <ExclamationTriangleIcon />,
  review: <PersonIcon />,
  running: <UpdateIcon />,
};

/** Every subject against every stage, one small cell each: the whole study at a glance.
 * A row opens that subject's page. Same states, words and colours as the status chips. */
export function PipelineMap({ subjects, onOpen }: { subjects: Row[]; onOpen: (label: string) => void }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const shown = useMemo(
    () => subjects.filter((r) => FILTERS[filter](r) && r.label.toLowerCase().includes(query.trim().toLowerCase())),
    [subjects, filter, query],
  );
  const count = (f: Filter) => subjects.filter(FILTERS[f]).length;
  return (
    <Card size="2">
      <Flex direction="column" gap={space.group}>
        <Flex justify="between" align="center" gap={space.group} wrap="wrap">
          <Heading as="h2" size={type.sectionTitle}>
            Pipeline map
          </Heading>
          <Flex gap={space.group} align="center" wrap="wrap">
            <TextField.Root size="1" placeholder="Find a subject" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search subjects">
              <TextField.Slot>
                <MagnifyingGlassIcon />
              </TextField.Slot>
            </TextField.Root>
            <SegmentedControl.Root size="1" value={filter} onValueChange={(v) => setFilter(v as Filter)}>
              <SegmentedControl.Item value="all">All {count("all")}</SegmentedControl.Item>
              <SegmentedControl.Item value="todo">To do {count("todo")}</SegmentedControl.Item>
              <SegmentedControl.Item value="attention">Needs you {count("attention")}</SegmentedControl.Item>
              <SegmentedControl.Item value="complete">Complete {count("complete")}</SegmentedControl.Item>
              {count("excluded") > 0 && <SegmentedControl.Item value="excluded">Excluded {count("excluded")}</SegmentedControl.Item>}
            </SegmentedControl.Root>
          </Flex>
        </Flex>
        <div className="pm-scroll">
          <table className="pm">
            <thead>
              <tr>
                <th>Subject</th>
                {COLUMNS.map(([id, label]) => (
                  <th key={id}>{label}</th>
                ))}
                <th>Quality</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr
                  key={r.label}
                  tabIndex={0}
                  data-excluded={r.qc_decision === "exclude"}
                  onClick={() => onOpen(r.label)}
                  onKeyDown={(e) => e.key === "Enter" && onOpen(r.label)}
                  title={r.last_activity ? `Last activity ${when(r.last_activity)}${r.last_activity_by ? ` by ${r.last_activity_by}` : ""}` : undefined}
                >
                  <td>
                    <Text weight="medium">{r.label}</Text>
                  </td>
                  {COLUMNS.map(([id, label]) => {
                    const c = r.stages.find((s) => s.id === id);
                    const state = c?.state ?? "unavailable";
                    return (
                      <td key={id}>
                        <Tooltip content={`${label}: ${c?.detail ?? stageLabel[state] ?? state}`}>
                          <span className="pm-cell" data-state={state}>
                            {ICON[state] ?? (state === "unavailable" ? "-" : "")}
                          </span>
                        </Tooltip>
                      </td>
                    );
                  })}
                  <td>
                    <Flex gap="1" align="center">
                      {r.qc_decision ? (
                        <Badge color={DECISION_COLOUR[r.qc_decision as "accept" | "review" | "exclude"]} variant="soft" size="1" title={r.qc_reason ?? undefined}>
                          {DECISION_LABEL[r.qc_decision as "accept" | "review" | "exclude"]}
                        </Badge>
                      ) : reviewable(r) ? (
                        <Text size={type.caption} color="gray">
                          No decision
                        </Text>
                      ) : null}
                      {r.motion_flag && (
                        <Badge color="amber" variant="soft" size="1" title={r.motion_flag}>
                          motion
                        </Badge>
                      )}
                    </Flex>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 && (
            <Text size={type.help} color="gray">
              No subject matches.
            </Text>
          )}
        </div>
      </Flex>
    </Card>
  );
}
