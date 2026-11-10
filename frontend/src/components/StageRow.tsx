import { MixerHorizontalIcon } from "@radix-ui/react-icons";
import { Badge, Button, Card, Flex, Switch, Text } from "@radix-ui/themes";
import type { StagePlan } from "../api/types";
import { space, type } from "../theme/tokens";

/** One stage on the Process page: a switch, its name, a one-line summary of its settings and a
 * Settings button. The settings themselves open in a side panel, so the page stays quiet. */
export function StageRow({
  label,
  plan,
  enabled,
  onToggle,
  summary,
  status,
  hasSettings,
  changed,
  onSettings,
}: {
  label: string;
  plan?: StagePlan;
  enabled: boolean;
  onToggle: (on: boolean) => void;
  summary: string;
  status?: { text: string; tone: "green" | "amber" | "gray" };
  hasSettings: boolean;
  changed: boolean;
  onSettings: () => void;
}) {
  const blocked = !!plan && !plan.can_run;
  return (
    <Card size="1" variant="surface" style={{ opacity: blocked ? 0.7 : 1 }}>
      <Flex align="center" gap={space.group}>
        <Switch checked={enabled && !blocked} disabled={blocked} onCheckedChange={onToggle} aria-label={`Include ${label}`} />
        <Flex direction="column" style={{ minWidth: 0, flex: 1 }}>
          <Flex align="center" gap="2" wrap="wrap">
            <Text weight="medium">{label}</Text>
            {status && (
              <Badge color={status.tone} variant="soft" size="1">
                {status.text}
              </Badge>
            )}
          </Flex>
          <Text size={type.caption} color="gray" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {blocked ? `Not possible: ${plan?.reason}` : summary}
          </Text>
        </Flex>
        {hasSettings && (
          <Button size="1" variant="soft" color="gray" onClick={onSettings} aria-label={`Settings for ${label}`}>
            <MixerHorizontalIcon />
            Settings
            {changed && <span aria-label="changed" title="Different from the defaults" style={{ width: 6, height: 6, borderRadius: 3, background: "var(--accent-9)" }} />}
          </Button>
        )}
      </Flex>
    </Card>
  );
}
