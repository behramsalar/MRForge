import { Badge } from "@radix-ui/themes";
import { actionColor, confidenceColor, stageColor, stageLabel, statusColor, statusLabel } from "../../theme/tokens";

export function ConfidenceBadge({ level }: { level: "High" | "Medium" | "Low" }) {
  return (
    <Badge color={confidenceColor[level]} variant="soft">
      {level}
    </Badge>
  );
}

const actionText = { import: "Will import", skip: "Skipped", ask: "Needs your input" } as const;

export function ActionBadge({ action }: { action: "import" | "skip" | "ask" }) {
  return (
    <Badge color={actionColor[action]} variant={action === "ask" ? "solid" : "soft"}>
      {actionText[action]}
    </Badge>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge color={statusColor[status] ?? "gray"} variant="soft">
      {statusLabel[status] ?? status}
    </Badge>
  );
}

/** Where a subject stands in one stage (dashboard table). */
export function StageBadge({ state, detail }: { state: string; detail?: string | null }) {
  return (
    <Badge color={stageColor[state] ?? "gray"} variant={state === "done" ? "soft" : "soft"}>
      {stageLabel[state] ?? state}
      {detail ? ` · ${detail}` : ""}
    </Badge>
  );
}
