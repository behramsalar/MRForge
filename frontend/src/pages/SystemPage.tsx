import { ReloadIcon } from "@radix-ui/react-icons";
import { Badge, Button, Callout, Card, Flex, Table, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { ErrorCallout } from "../components/ErrorCallout";
import { PageHeader } from "../components/ui/Layout";
import { space, type } from "../theme/tokens";

const badge = {
  PASS: { color: "green", text: "Found" },
  FAIL: { color: "red", text: "Missing" },
  OPTIONAL: { color: "gray", text: "Not installed (optional)" },
  INFO: { color: "blue", text: "" },
} as const;

/** Is this computer ready for MRForge? The same checks as `mrforge doctor`, with what to do
 * about anything that is missing. */
export function SystemPage() {
  const system = useQuery({ queryKey: ["system"], queryFn: () => call(api.GET("/api/system")) });
  const s = system.data;
  const problems = s?.checks.filter((c) => c.fix && (c.status === "FAIL" || c.status === "OPTIONAL")) ?? [];
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader title="System" description="Whether this computer has what MRForge needs to process data." />
      {system.error && <ErrorCallout error={(system.error as ApiError).body} />}
      {s && (
        <>
          <Callout.Root color={s.ready ? "green" : "red"}>
            <Callout.Text>
              {s.ready
                ? "Everything MRForge needs is in place."
                : "Something MRForge needs is missing. Processing will not work until it is fixed (see below)."}
            </Callout.Text>
          </Callout.Root>
          <Card size="3">
            <Flex direction="column" gap={space.group}>
              <Flex justify="between" align="center">
                <Text size={type.help} color="gray">
                  MRForge {s.version} · workspaces in {s.workspaces_root}
                </Text>
                <Button variant="soft" disabled={system.isFetching} onClick={() => system.refetch()}>
                  <ReloadIcon /> Check again
                </Button>
              </Flex>
              <Table.Root>
                <Table.Body>
                  {s.checks.map((c) => (
                    <Table.Row key={c.name}>
                      <Table.RowHeaderCell>{c.name}</Table.RowHeaderCell>
                      <Table.Cell>
                        {c.status === "INFO" ? null : (
                          <Badge color={badge[c.status].color} variant="soft">
                            {badge[c.status].text}
                          </Badge>
                        )}
                      </Table.Cell>
                      <Table.Cell>
                        <Text size={type.help} style={{ wordBreak: "break-all" }}>
                          {c.detail}
                        </Text>
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table.Root>
            </Flex>
          </Card>
          {problems.length > 0 && (
            <Card size="3">
              <Flex direction="column" gap={space.group}>
                <Text weight="bold">What to do</Text>
                {problems.map((c) => (
                  <Text key={c.name} size={type.help}>
                    <strong>{c.name}:</strong> {c.fix}
                  </Text>
                ))}
              </Flex>
            </Card>
          )}
        </>
      )}
    </Flex>
  );
}
