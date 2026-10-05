import { Button, Card, Flex, Heading, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";
import { useRoute } from "../../lib/router";
import { navItemFor } from "../../shell/nav";
import { areaColor, space, type } from "../../theme/tokens";

/** Title, one explaining sentence and the page's main buttons. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  const item = navItemFor(useRoute().page);
  const Icon = item?.icon;
  const color = areaColor[item?.id ?? ""] ?? "gray";
  return (
    <Flex justify="between" align="end" gap={space.group} wrap="wrap">
      <Flex gap={space.group} align="center" style={{ minWidth: 0 }}>
        {Icon && (
          <Flex
            align="center"
            justify="center"
            aria-hidden
            style={{ width: 48, height: 48, flex: "none", borderRadius: "var(--radius-4)", background: `var(--${color}-a3)`, color: `var(--${color}-10)` }}
          >
            <Icon width={24} height={24} />
          </Flex>
        )}
        <Flex direction="column" gap="1" style={{ minWidth: 0 }}>
          <Heading size={type.pageTitle}>{title}</Heading>
          {description && (
            <Text color="gray" size={type.body}>
              {description}
            </Text>
          )}
        </Flex>
      </Flex>
      {actions && <Flex gap={space.inline}>{actions}</Flex>}
    </Flex>
  );
}

/** A number with a label, for the dashboard. */
export function StatCard({
  label,
  value,
  hint,
  color,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  color?: string; // a Radix colour name
  icon?: ReactNode;
}) {
  return (
    <Card size="3">
      <Flex gap={space.group} align="center">
        {icon && (
          <Flex
            align="center"
            justify="center"
            style={{
              width: 44,
              height: 44,
              borderRadius: "var(--radius-4)",
              background: color ? `var(--${color}-a3)` : "var(--gray-a3)",
              color: color ? `var(--${color}-11)` : "var(--gray-11)",
            }}
          >
            {icon}
          </Flex>
        )}
        <Flex direction="column">
          <Text size={type.help} color="gray">
            {label}
          </Text>
          <Text size="7" weight="bold" style={{ lineHeight: 1.1 }}>
            {value}
          </Text>
          {hint && (
            <Text size={type.caption} color="gray">
              {hint}
            </Text>
          )}
        </Flex>
      </Flex>
    </Card>
  );
}

/** An invitation instead of an apology: what this space is for, and the button to start. */
export function EmptyState({
  title,
  text,
  action,
  onAction,
  href,
  icon,
  children,
}: {
  title: string;
  text: string;
  action?: string;
  onAction?: () => void;
  href?: string;
  icon?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <Card size="4">
      <Flex direction="column" align="center" gap={space.group} py="6">
        {icon && <Text color="gray">{icon}</Text>}
        <Heading as="h2" size={type.sectionTitle}>{title}</Heading>
        <Text color="gray" size={type.body} align="center" style={{ maxWidth: 460 }}>
          {text}
        </Text>
        {action && (
          <Button size="3" asChild={!!href} onClick={onAction}>
            {href ? <a href={href}>{action}</a> : action}
          </Button>
        )}
        {children}
      </Flex>
    </Card>
  );
}
