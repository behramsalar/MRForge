import { SegmentedControl } from "@radix-ui/themes";
import { Flex } from "@radix-ui/themes";
import type { WorkspaceState } from "../api/types";
import { href } from "../lib/router";
import { space } from "../theme/tokens";
import { AnatomicalPage } from "./AnatomicalPage";
import { FullProcessingPage } from "./FullProcessingPage";
import { FunctionalPage } from "./FunctionalPage";

/**
 * Process: "Pipelines" (the recommended way: complete processing with settings you confirm)
 * and "Single steps" (one step at a time, for advanced use). New pipelines are added inside
 * the Pipelines tab and new steps inside Single steps, so the sidebar does not grow.
 */
export function ProcessPage({
  ws,
  tab,
  sub,
  state,
}: {
  ws: string;
  tab?: string;
  sub?: string;
  state: WorkspaceState | null;
}) {
  const current = tab === "steps" ? "steps" : "pipelines";
  const step = sub === "func" ? "func" : "anat";
  const go = (...parts: string[]) => {
    location.hash = href(ws, "process", ...parts);
  };
  return (
    <Flex direction="column" gap={space.section}>
      <Flex gap={space.group} wrap="wrap" align="center">
        <SegmentedControl.Root value={current} onValueChange={(v) => go(v)}>
          <SegmentedControl.Item value="pipelines">Pipelines</SegmentedControl.Item>
          <SegmentedControl.Item value="steps">Single steps</SegmentedControl.Item>
        </SegmentedControl.Root>
        {current === "steps" && (
          <SegmentedControl.Root value={step} onValueChange={(v) => go("steps", v)}>
            <SegmentedControl.Item value="anat">Anatomical</SegmentedControl.Item>
            <SegmentedControl.Item value="func">Functional</SegmentedControl.Item>
          </SegmentedControl.Root>
        )}
      </Flex>
      {current === "pipelines" && <FullProcessingPage ws={ws} state={state} />}
      {current === "steps" && step === "anat" && <AnatomicalPage ws={ws} state={state} />}
      {current === "steps" && step === "func" && <FunctionalPage ws={ws} state={state} />}
    </Flex>
  );
}
