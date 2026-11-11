import { Dialog, Flex, Text } from "@radix-ui/themes";

const MAC = typeof navigator !== "undefined" && /Mac/.test(navigator.platform);
export const modKey = MAC ? "⌘" : "Ctrl";

const ROWS: [string, string][] = [
  [`${modKey} K`, "Jump to a page, subject or action"],
  ["?", "Show this list"],
  ["Esc", "Close a window"],
  ["↑ ↓ and Enter", "Move and choose inside the jump list"],
];

/** Inside the quality inspector (a subject opened from the Quality page). */
const REVIEW_ROWS: [string, string][] = [
  ["← →  or  k j", "Previous / next subject"],
  ["A  R  X", "Accept, mark for review, exclude (then give a reason; Enter saves)"],
  ["1 2 3 4", "Switch the check shown"],
];

/** Only shortcuts that exist are listed; more are added here as screens get them. */
export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="420px">
        <Dialog.Title size="4">Keyboard shortcuts</Dialog.Title>
        <Flex direction="column" gap="2" mt="3">
          {ROWS.map(([k, d]) => (
            <Flex key={k} justify="between" gap="4" align="center">
              <Text size="2">{d}</Text>
              <kbd className="kbd">{k}</kbd>
            </Flex>
          ))}
          <Text size="2" weight="medium" mt="2">
            Quality review
          </Text>
          {REVIEW_ROWS.map(([k, d]) => (
            <Flex key={k} justify="between" gap="4" align="center">
              <Text size="2">{d}</Text>
              <kbd className="kbd">{k}</kbd>
            </Flex>
          ))}
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
