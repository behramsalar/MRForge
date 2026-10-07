import { Button, Callout, Card, Flex, Heading, Table, Text } from "@radix-ui/themes";
import { ActionBadge, ConfidenceBadge, StatusBadge } from "../components/ui/Badges";
import { layout, space, type } from "../theme/tokens";

/** A living reference of the building blocks (open with ?page=design). */
export function DesignSystem() {
  return (
    <Flex direction="column" gap={space.section} p={space.page} maxWidth={layout.contentWidth} mx="auto">
      <Heading size={type.pageTitle}>MRForge design system</Heading>
      <Text size={type.help} color="gray">
        Everything below comes from src/theme/tokens.ts and Radix Themes. New screens reuse these
        pieces instead of inventing new styles.
      </Text>

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
