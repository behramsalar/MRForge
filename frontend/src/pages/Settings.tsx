import { Badge, Card, Flex, Heading, SegmentedControl, Table, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { ErrorCallout } from "../components/ErrorCallout";
import { PageHeader } from "../components/ui/Layout";
import { useAppTheme, type Mode } from "../shell/ThemeProvider";
import { space, type } from "../theme/tokens";

const toolName: Record<string, string> = {
  fsl: "FSL",
  dcm2niix: "dcm2niix (DICOM conversion)",
  "bids-validator": "BIDS validator",
};

export function Settings() {
  const { mode, setMode } = useAppTheme();
  const health = useQuery({ queryKey: ["health"], queryFn: () => call(api.GET("/api/health")) });
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader title="Settings" description="How MRForge looks, and which tools it found on this computer." />
      <Card size="3">
        <Flex direction="column" gap={space.group}>
          <Heading size={type.sectionTitle}>Appearance</Heading>
          <SegmentedControl.Root value={mode} onValueChange={(v) => setMode(v as Mode)} style={{ alignSelf: "flex-start" }}>
            <SegmentedControl.Item value="light">Light</SegmentedControl.Item>
            <SegmentedControl.Item value="dark">Dark</SegmentedControl.Item>
            <SegmentedControl.Item value="system">Follow my computer</SegmentedControl.Item>
          </SegmentedControl.Root>
        </Flex>
      </Card>
      <Card size="3">
        <Flex direction="column" gap={space.group}>
          <Heading size={type.sectionTitle}>Tools and folders</Heading>
          {health.error && <ErrorCallout error={(health.error as ApiError).body} />}
          {health.data && (
            <>
              <Table.Root>
                <Table.Body>
                  {Object.entries(health.data.tools).map(([key, version]) => (
                    <Table.Row key={key}>
                      <Table.RowHeaderCell>{toolName[key] ?? key}</Table.RowHeaderCell>
                      <Table.Cell>
                        {version ? (
                          <Badge color="green" variant="soft">
                            Found{version !== "installed" ? `, version ${version}` : ""}
                          </Badge>
                        ) : (
                          <Badge color="red" variant="soft">
                            Not found
                          </Badge>
                        )}
                      </Table.Cell>
                    </Table.Row>
                  ))}
                  <Table.Row>
                    <Table.RowHeaderCell>Workspaces folder</Table.RowHeaderCell>
                    <Table.Cell>
                      <Text size={type.help}>{health.data.workspaces_root}</Text>
                    </Table.Cell>
                  </Table.Row>
                  <Table.Row>
                    <Table.RowHeaderCell>MRForge version</Table.RowHeaderCell>
                    <Table.Cell>
                      <Text size={type.help}>{health.data.version}</Text>
                    </Table.Cell>
                  </Table.Row>
                </Table.Body>
              </Table.Root>
            </>
          )}
        </Flex>
      </Card>
    </Flex>
  );
}
