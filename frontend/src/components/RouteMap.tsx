import { ArrowRightIcon } from "@radix-ui/react-icons";
import { Card, Flex, Heading, Text } from "@radix-ui/themes";
import { Fragment } from "react";
import type { Overview } from "../api/types";
import { OVERVIEW_ID, STAGE_NAME, type Goal } from "../lib/goals";
import { space, type } from "../theme/tokens";
import "./overview.css";

type Row = Overview["subjects"][number];

/** Where a stage stands for the chosen subjects, in plain words. */
function caption(id: string, rows: Row[]): { text: string; state: string } {
  if (rows.length === 0) return { text: "", state: "none" };
  const states = rows.map((r) => r.stages.find((c) => c.id === OVERVIEW_ID[id])?.state ?? "none");
  const n = (s: string) => states.filter((x) => x === s).length;
  if (rows.length === 1) {
    const s = states[0];
    if (s === "done") return { text: "Done earlier", state: "done" };
    if (s === "unavailable") return { text: "Not possible", state: "unavailable" };
    if (s === "running") return { text: "Running", state: "running" };
    if (s === "failed" || s === "stopped") return { text: "Will run again", state: s };
    if (s === "review") return { text: "Waiting for you", state: "review" };
    return { text: "Will run", state: "none" };
  }
  const bits = [
    n("done") ? `${n("done")} done earlier` : "",
    n("unavailable") ? `${n("unavailable")} not possible` : "",
  ].filter(Boolean);
  return { text: bits.join(" · ") || "Will run", state: n("done") === rows.length ? "done" : "none" };
}

/** The route a goal takes: the stages in order, the optional one drawn dashed, and for the
 * chosen subjects what is already done. Purely a picture of the choice; the confirmation
 * dialog stays the single place that says what will really run. */
export function RouteMap({ goal, withArtifact, rows }: { goal: Goal; withArtifact: boolean; rows: Row[] }) {
  return (
    <Card size="2">
      <Flex direction="column" gap={space.group}>
        <Flex justify="between" align="baseline" gap={space.group} wrap="wrap">
          <Heading as="h2" size={type.sectionTitle}>
            What will run
          </Heading>
          <Text size={type.caption} color="gray">
            {rows.length === 0 ? "Choose subjects below to see what is already done." : "Stages already done are not repeated if nothing changed."}
          </Text>
        </Flex>
        <div className="route" role="list" aria-label={`Route for ${goal.title}`}>
          {goal.route.map((id, i) => {
            const optional = id === "artifact_rejection" && goal.id !== "full";
            const included = !optional || withArtifact;
            const full = goal.id === "full" && id === "artifact_rejection";
            const cap = caption(id, rows);
            return (
              <Fragment key={id}>
                {i > 0 && <ArrowRightIcon className="route-arrow" aria-hidden />}
                <div className="route-node" role="listitem" data-state={cap.state} data-off={!included} data-optional={optional || full}>
                  <span className="route-name">{STAGE_NAME[id]}</span>
                  <span className="route-cap">
                    {!included ? "Not included" : full ? "Optional: you choose next" : cap.text || " "}
                  </span>
                </div>
              </Fragment>
            );
          })}
        </div>
      </Flex>
    </Card>
  );
}
