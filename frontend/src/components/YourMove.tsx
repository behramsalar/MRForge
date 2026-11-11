import { CheckCircledIcon } from "@radix-ui/react-icons";
import { Button, Card, Flex, Heading, Text } from "@radix-ui/themes";
import type { Overview } from "../api/types";
import { yourMove } from "../lib/overviewSummary";
import { space, type } from "../theme/tokens";
import "./overview.css";

/** What waits for the researcher, each with the button that does it. */
export function YourMove({ ws, o }: { ws: string; o: Overview }) {
  const moves = yourMove(o);
  return (
    <Card size="2">
      <Flex direction="column" gap={space.group}>
        <Heading as="h2" size={type.sectionTitle}>
          Needs your decision
        </Heading>
        {moves.length === 0 && (
          <Flex align="center" gap="2">
            <CheckCircledIcon color="var(--green-9)" />
            <Text size={type.help} color="gray">
              Nothing needs you right now.
            </Text>
          </Flex>
        )}
        {moves.slice(0, 6).map((m) => (
          <div key={m.id} className="move" data-tone={m.tone}>
            <Text size={type.help} weight="bold">
              {m.title}
            </Text>
            <Text size={type.caption} color="gray">
              {m.text}
            </Text>
            <Flex>
              <Button size="1" variant="soft" asChild>
                <a href={`#/w/${encodeURIComponent(ws)}/${m.to}`}>{m.action}</a>
              </Button>
            </Flex>
          </div>
        ))}
        {moves.length > 6 && (
          <Text size={type.caption} color="gray">
            and {moves.length - 6} more. Fix these first; the list updates.
          </Text>
        )}
      </Flex>
    </Card>
  );
}
