import { Card, Flex, Text } from "@radix-ui/themes";
import type { Overview } from "../api/types";
import { processSegments, qualityCounts, type Segment } from "../lib/overviewSummary";
import { space, type } from "../theme/tokens";
import "./overview.css";

export function SegBar({ parts, total }: { parts: { key: string; n: number }[]; total: number }) {
  return (
    <div className="seg-bar" aria-hidden="true">
      {parts
        .filter((p) => p.n > 0 && total > 0)
        .map((p) => (
          <i key={p.key} data-k={p.key} style={{ width: `${(100 * p.n) / total}%` }} />
        ))}
    </div>
  );
}

function Journey({
  n,
  title,
  sub,
  bar,
  children,
}: {
  n: number;
  title: string;
  sub: string;
  bar: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card size="2">
      <Flex direction="column" gap="2">
        <Flex align="baseline" gap="2">
          <Text size={type.help} color="gray" weight="bold">
            {n}
          </Text>
          <Text size={type.body} weight="bold">
            {title}
          </Text>
        </Flex>
        <Text size={type.caption} color="gray">
          {sub}
        </Text>
        {bar}
        <Text size={type.help}>{children}</Text>
      </Flex>
    </Card>
  );
}

const num = (n: number, word: string, color?: "amber" | "red" | "green") => (
  <>
    <Text weight="bold" color={color}>
      {n}
    </Text>{" "}
    {word}
  </>
);

/** The four steps of a study at a glance: Import, Process, Check quality, Results. */
export function OverviewCards({ o, importsNeedingYou }: { o: Overview; importsNeedingYou: number }) {
  const seg = processSegments(o.subjects);
  const count = (k: Segment["key"]) => seg.find((s) => s.key === k)?.n ?? 0;
  const q = qualityCounts(o.subjects);
  const complete = o.subjects.filter((r) => r.complete && r.qc_decision !== "exclude").length;
  const total = o.subjects_total;
  return (
    <div className="ov-grid" style={{ display: "grid", gap: `var(--space-${space.group})`, gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>
      <Journey
        n={1}
        title="Import"
        sub="Scanner data in, organised."
        bar={<SegBar parts={[{ key: "done", n: total }]} total={total} />}
      >
        {num(total, total === 1 ? "subject imported" : "subjects imported")}
        {importsNeedingYou > 0 && <>, {num(importsNeedingYou, "needs you", "amber")}</>}
      </Journey>
      <Journey
        n={2}
        title="Process"
        sub="Clean each scan, align to a template."
        bar={<SegBar parts={seg} total={total} />}
      >
        {num(count("done"), "finished")}
        {count("running") > 0 && <>, {num(count("running"), "running")}</>}
        {count("waiting") > 0 && <>, {num(count("waiting"), "waiting for you", "amber")}</>}
        {count("failed") > 0 && <>, {num(count("failed"), "failed", "red")}</>}
      </Journey>
      <Journey
        n={3}
        title="Check quality"
        sub="Keep, review or exclude each subject."
        bar={
          <SegBar
            parts={[
              { key: "done", n: q.decided - o.excluded },
              { key: "excluded", n: o.excluded },
              { key: "waiting", n: q.undecided },
            ]}
            total={q.total}
          />
        }
      >
        {q.total === 0 ? "Nothing to check yet" : <>{num(q.decided, `of ${q.total} decided`)}{q.undecided > 0 && <>, {num(q.undecided, "waiting for you", "amber")}</>}</>}
      </Journey>
      <Journey
        n={4}
        title="Results"
        sub="Finished subjects, ready to use."
        bar={<SegBar parts={[{ key: "done", n: complete }]} total={total} />}
      >
        {num(complete, complete === 1 ? "subject complete" : "subjects complete")}
        {o.excluded > 0 && <>, {num(o.excluded, "excluded")}</>}
      </Journey>
    </div>
  );
}
