import { Button, Card, Flex, Text } from "@radix-ui/themes";
import { useState } from "react";
import { useOverview } from "../api/hooks";
import type { WorkspaceState } from "../api/types";
import { ConfirmProcessDialog } from "../components/ConfirmProcessDialog";
import { StageChips } from "../components/StageChips";
import { SubjectsTable } from "../components/SubjectsTable";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

/** One processing stage on its own, for a subject whose earlier stages are done. The stage list
 * and the settings come from the plan, so this page only chooses the subject and the stage. */
export function StagePage({
  ws,
  state,
  stage,
  title,
  description,
  hint = "Choose a subject. The earlier stages must be done already; their results are used as they are.",
  multi = false,
}: {
  ws: string;
  state: WorkspaceState | null;
  stage: string;
  title: string;
  description: string;
  hint?: string;
  multi?: boolean; // choose several subjects and run the stage for all of them with the same settings
}) {
  const overview = useOverview(ws);
  const [chosenList, setChosen] = useState<string[]>([]);
  const [confirm, setConfirm] = useState(false);
  const rows = (overview.data?.subjects ?? []).filter((s) => s.n_files > 0);
  const picked = rows.filter((s) => chosenList.includes(s.label));
  const row = !multi ? picked[0] : undefined;
  const several = multi && picked.length > 0;
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader title={title} description={description} />
      {overview.data && rows.length === 0 && (
        <EmptyState title="There is no data to process yet" text="Import your scans first." action="Import scans" href={href(ws, "data")} />
      )}
      {rows.length > 0 && (
        <>
          <Text size={type.help} color="gray">
            {hint}
          </Text>
          <SubjectsTable
            subjects={rows}
            multi={multi}
            selected={chosenList}
            onSelect={(l) => setChosen(multi ? l : l.slice(0, 1))}
          />
        </>
      )}
      {row && (
        <Card size="3">
          <Flex gap={space.group} align="center" wrap="wrap" justify="between">
            <Flex direction="column" gap="1">
              <Text weight="bold">{row.label}</Text>
              <StageChips stages={row.stages} />
            </Flex>
            <Button size="3" disabled={busy} onClick={() => setConfirm(true)}>
              Run {title.replace(/\s*\(.*\)/, "").toLowerCase()} for {row.label}…
            </Button>
          </Flex>
        </Card>
      )}
      {several && (
        <Card size="3">
          <Flex gap={space.group} align="center" wrap="wrap" justify="between">
            <Flex direction="column" gap="1">
              <Text weight="bold">
                {picked.length} subject{picked.length === 1 ? "" : "s"} selected
              </Text>
              <Text size={type.help} color="gray">
                The same settings are used for all of them. Subjects without the needed data are listed and skipped.
              </Text>
            </Flex>
            <Button size="3" disabled={busy} onClick={() => setConfirm(true)}>
              Run {title.replace(/\s*\(.*\)/, "").toLowerCase()} for {picked.length} subject{picked.length === 1 ? "" : "s"}…
            </Button>
          </Flex>
        </Card>
      )}
      {row && <ConfirmProcessDialog ws={ws} subject={row.label} open={confirm} onOpenChange={setConfirm} onlyStage={stage} />}
      {several && (
        <ConfirmProcessDialog
          ws={ws}
          subject={picked[0].label}
          subjects={picked.map((s) => s.label)}
          open={confirm}
          onOpenChange={setConfirm}
          onlyStage={stage}
        />
      )}
    </Flex>
  );
}
