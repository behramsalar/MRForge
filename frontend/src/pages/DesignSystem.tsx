import { Badge, Button, Callout, Card, Flex, Heading, Progress, SegmentedControl, Table, Text } from "@radix-ui/themes";
import { ActionBadge, ConfidenceBadge, StatusBadge } from "../components/ui/Badges";
import { useAppTheme } from "../shell/ThemeProvider";
import { layout, palettes, space, type } from "../theme/tokens";

/** A living reference of the building blocks (open with ?page=design). */
export function DesignSystem() {
  const { palette, setPalette } = useAppTheme();
  return (
    <Flex direction="column" gap={space.section} p={space.page} maxWidth={layout.contentWidth} mx="auto">
      <Heading size={type.pageTitle}>MRForge design system</Heading>
      <Text size={type.help} color="gray">
        Everything below comes from src/theme/tokens.ts and Radix Themes. New screens reuse these
        pieces instead of inventing new styles.
      </Text>

      <Heading as="h2" size={type.sectionTitle}>Palette (provisional)</Heading>
      <Text size={type.help} color="gray">
        Each palette is an accent colour together with its own colours for done, needs you, failed, running and stopped. Pick one to try it on every screen. Remembered in this browser only; the final
        choice will be written into tokens.ts.
      </Text>
      <SegmentedControl.Root value={palette} onValueChange={setPalette}>
        {palettes.map((o) => (
          <SegmentedControl.Item key={o.id} value={o.id}>
            {o.label}
          </SegmentedControl.Item>
        ))}
      </SegmentedControl.Root>

      <Flex gap={space.inline} wrap="wrap" align="center">
        <Badge color="green">Done</Badge>
        <Badge color="amber">Needs you</Badge>
        <Badge color="red">Failed</Badge>
        <Badge color="blue">Running</Badge>
        <Badge color="orange">Stopped early</Badge>
        <Badge>Accent</Badge>
        <Progress value={60} style={{ width: 120 }} aria-label="example" />
        <Progress value={100} color="green" style={{ width: 120 }} aria-label="example done" />
      </Flex>

      <Heading as="h2" size={type.sectionTitle}>Buttons</Heading>
      <Flex gap={space.group}>
        <Button>Import series</Button>
        <Button variant="soft">Set task</Button>
        <Button variant="outline">View log</Button>
        <Button color="red" variant="soft">
          Cancel
        </Button>
      </Flex>

      <Heading as="h2" size={type.sectionTitle}>Status and confidence</Heading>
      <Flex gap={space.inline} wrap="wrap">
        {["Queued", "Running", "Completed", "Failed", "Interrupted", "Waiting", "Cancelled"].map((s) => (
          <StatusBadge key={s} status={s} />
        ))}
        <ConfidenceBadge level="High" />
        <ConfidenceBadge level="Medium" />
        <ConfidenceBadge level="Low" />
        <ActionBadge action="import" />
        <ActionBadge action="skip" />
        <ActionBadge action="ask" />
      </Flex>

      <Heading as="h2" size={type.sectionTitle}>Messages</Heading>
      <Callout.Root color="amber">
        <Callout.Text>2 series need your input. They are not imported until you decide.</Callout.Text>
      </Callout.Root>

      <Heading as="h2" size={type.sectionTitle}>Table</Heading>
      <Card>
        <Table.Root>
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeaderCell>Series</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Detected</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>Confidence</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>What happens</Table.ColumnHeaderCell>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            <Table.Row>
              <Table.RowHeaderCell>2 t1w</Table.RowHeaderCell>
              <Table.Cell>anat / T1w</Table.Cell>
              <Table.Cell><ConfidenceBadge level="High" /></Table.Cell>
              <Table.Cell><ActionBadge action="import" /></Table.Cell>
            </Table.Row>
            <Table.Row>
              <Table.RowHeaderCell>19 ep2d_bold</Table.RowHeaderCell>
              <Table.Cell>func / bold</Table.Cell>
              <Table.Cell><ConfidenceBadge level="Medium" /></Table.Cell>
              <Table.Cell><ActionBadge action="ask" /></Table.Cell>
            </Table.Row>
          </Table.Body>
        </Table.Root>
      </Card>
    </Flex>
  );
}
