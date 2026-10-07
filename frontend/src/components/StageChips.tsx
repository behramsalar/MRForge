import { CheckIcon, Cross2Icon, ExclamationTriangleIcon, PersonIcon, UpdateIcon } from "@radix-ui/react-icons";
import { Badge, Flex, Tooltip } from "@radix-ui/themes";
import type { ReactNode } from "react";
import type { StageChip } from "../api/types";
import { stageColor, stageLabel } from "../theme/tokens";

const ICONS: Record<string, ReactNode> = {
  done: <CheckIcon />,
  failed: <Cross2Icon />,
  stopped: <ExclamationTriangleIcon />,
  review: <PersonIcon />,
  running: <UpdateIcon />,
};

/** The stages of a subject as small chips: same words, order and colours on every page.
 * Done is green with a check; a stage that is optional and not done is plain grey. */
export function StageChips({ stages, skip = ["import"] }: { stages: StageChip[]; skip?: string[] }) {
  return (
    <Flex gap="1" wrap="wrap">
      {stages
        .filter((c) => !skip.includes(c.id) && c.state !== "unavailable")
        .map((c) => (
          <Tooltip key={c.id} content={`${c.label}: ${c.detail ?? stageLabel[c.state] ?? c.state}`}>
            <Badge color={stageColor[c.state] ?? "gray"} variant={c.state === "done" ? "solid" : "soft"} size="1">
              {ICONS[c.state]}
              {c.label}
            </Badge>
          </Tooltip>
        ))}
    </Flex>
  );
}
