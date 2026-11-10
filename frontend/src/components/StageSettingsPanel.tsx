import { Cross2Icon } from "@radix-ui/react-icons";
import { Button, Dialog, Flex, IconButton, Text } from "@radix-ui/themes";
import type { FullOptions } from "../api/types";
import { resetStage, settingsChanged } from "../lib/processOptions";
import { space, type } from "../theme/tokens";
import { StageSettings } from "./StageSettings";

/** The settings of one stage, in a panel that slides in from the right. The same choices apply to
 * every subject of the run. */
export function StageSettingsPanel({
  stageId,
  label,
  description,
  opts,
  setOpts,
  onClose,
}: {
  stageId: string | null;
  label: string;
  description?: string;
  opts: FullOptions;
  setOpts: (o: FullOptions) => void;
  onClose: () => void;
}) {
  return (
    <Dialog.Root open={!!stageId} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Content
        aria-describedby={undefined}
        style={{ position: "fixed", top: 0, right: 0, bottom: 0, margin: 0, width: "min(460px, 100vw)", maxWidth: "none", height: "100%", maxHeight: "none", borderRadius: 0, overflowY: "auto" }}
      >
        <Flex justify="between" align="start" gap={space.group}>
          <Dialog.Title mb="1">{label}: settings</Dialog.Title>
          <Dialog.Close>
            <IconButton variant="ghost" color="gray" aria-label="Close">
              <Cross2Icon />
            </IconButton>
          </Dialog.Close>
        </Flex>
        {description && (
          <Text as="p" size={type.help} color="gray" mb="4">
            {description}
          </Text>
        )}
        {stageId && <StageSettings stageId={stageId} opts={opts} setOpts={setOpts} />}
        <Flex justify="between" mt="5" gap={space.group}>
          <Button variant="soft" color="gray" disabled={!stageId || !settingsChanged(stageId, opts)} onClick={() => stageId && setOpts(resetStage(stageId, opts))}>
            Reset to defaults
          </Button>
          <Button onClick={onClose}>Done</Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
