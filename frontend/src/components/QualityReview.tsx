import { Card, Flex, SegmentedControl, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import type { Overview } from "../api/types";
import { CHECKS, SHOW_FILTER, type CheckId, type Show } from "../lib/qualityReview";
import { space, type } from "../theme/tokens";
import { QualityGrid } from "./QualityGrid";
import { QualityInspector } from "./QualityInspector";
import { QualityTable } from "./QualityTable";

type Row = Overview["subjects"][number];

/** The review: choose who to look at (needs a decision, flagged, all) and how (a grid of one picture
 * per subject for a chosen check, or a list), open a subject to inspect and decide. */
export function QualityReview({ ws, subjects }: { ws: string; subjects: Row[] }) {
  const [show, setShow] = useState<Show>("todo");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [check, setCheck] = useState<CheckId>("t1");
  const [open, setOpen] = useState<string | null>(null);
  const shown = useMemo(() => subjects.filter(SHOW_FILTER[show]), [subjects, show]);
  const count = (s: Show) => subjects.filter(SHOW_FILTER[s]).length;
  // The inspector walks through the list as shown and, after a decision, moves on to the next subject.
  const labels = useMemo(() => shown.map((r) => r.label), [shown]);
  return (
    <Card size="2">
      <Flex direction="column" gap={space.group}>
        <Flex gap={space.group} align="center" wrap="wrap" justify="between">
          <SegmentedControl.Root size="1" value={show} onValueChange={(v) => setShow(v as Show)}>
            <SegmentedControl.Item value="todo">Needs a decision {count("todo")}</SegmentedControl.Item>
            <SegmentedControl.Item value="flagged">Flagged {count("flagged")}</SegmentedControl.Item>
            <SegmentedControl.Item value="all">All {count("all")}</SegmentedControl.Item>
          </SegmentedControl.Root>
          <Flex gap={space.group} align="center" wrap="wrap">
            {view === "grid" && (
              <SegmentedControl.Root size="1" value={check} onValueChange={(v) => setCheck(v as CheckId)}>
                {CHECKS.map((c) => (
                  <SegmentedControl.Item key={c.id} value={c.id}>
                    {c.label}
                  </SegmentedControl.Item>
                ))}
              </SegmentedControl.Root>
            )}
            <SegmentedControl.Root size="1" value={view} onValueChange={(v) => setView(v as "grid" | "list")}>
              <SegmentedControl.Item value="grid">Pictures</SegmentedControl.Item>
              <SegmentedControl.Item value="list">List</SegmentedControl.Item>
            </SegmentedControl.Root>
          </Flex>
        </Flex>
        {shown.length === 0 ? (
          <Text size={type.help} color="gray">
            {show === "todo" ? "Nobody is waiting for a decision." : "No subject matches."}
          </Text>
        ) : view === "grid" ? (
          <QualityGrid ws={ws} subjects={shown} check={check} onOpen={setOpen} />
        ) : (
          <QualityTable ws={ws} subjects={shown} onOpen={setOpen} />
        )}
        <Text size={type.caption} color="gray">
          Click a subject to look closer and decide. MRForge flags problems; it never excludes anyone by itself.
        </Text>
      </Flex>
      <QualityInspector ws={ws} rows={subjects} labels={labels} current={open} check={check} onCheck={setCheck} onNavigate={setOpen} onClose={() => setOpen(null)} />
    </Card>
  );
}
