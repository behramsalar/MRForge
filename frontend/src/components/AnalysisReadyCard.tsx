import { CheckCircledIcon, CopyIcon, ExclamationTriangleIcon } from "@radix-ui/react-icons";
import { Button, Callout, Card, Code, Flex, Heading, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { call } from "../api/call";
import { space, type } from "../theme/tokens";

/** The final file of every recording, in one folder, for group analysis; and a warning when
 * those files were not all made the same way. */
export function AnalysisReadyCard({ ws, subjectsWithRuns }: { ws: string; subjectsWithRuns: number }) {
  const ready = useQuery({
    queryKey: ["ws", ws, "analysis-ready"],
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/analysis-ready", { params: { path: { ws_id: ws } } })),
    refetchInterval: 15000,
  });
  const [copied, setCopied] = useState(false);
  const d = ready.data;
  if (!d || d.rows.length === 0) return null;
  const subjects = new Set(d.rows.map((r) => r.subject)).size;
  return (
    <Card size="3">
      <Flex direction="column" gap={space.group}>
        <Flex gap={space.inline} align="center">
          <CheckCircledIcon color="var(--green-9)" />
          <Heading as="h2" size={type.sectionTitle}>
            Ready for group analysis
          </Heading>
        </Flex>
        <Text size={type.help}>
          {d.rows.length} recording{d.rows.length === 1 ? "" : "s"} of {subjects} subject{subjects === 1 ? "" : "s"}
          {subjectsWithRuns > 0 ? ` (of ${subjectsWithRuns} with functional data)` : ""} have their final file in one folder, all
          with the same name pattern (<Code>…_desc-final_bold</Code>), next to a list that says how each was made.
        </Text>
        <Flex gap={space.inline} align="center" wrap="wrap">
          <Code size="1" style={{ wordBreak: "break-all" }}>
            {d.folder}
          </Code>
          <Button
            size="1"
            variant="soft"
            color="gray"
            onClick={() => {
              void navigator.clipboard?.writeText(d.folder).then(() => setCopied(true));
            }}
          >
            <CopyIcon /> {copied ? "Copied" : "Copy path"}
          </Button>
        </Flex>
        {d.differences.length > 0 && (
          <Callout.Root color="amber">
            <Callout.Icon>
              <ExclamationTriangleIcon />
            </Callout.Icon>
            <Flex direction="column" gap="1">
              <Text weight="bold">These files were not all made the same way</Text>
              <Text size={type.help}>
                A group analysis should use files processed alike. Differences found:
              </Text>
              {d.differences.map((x) => (
                <Text key={x.setting} size={type.help}>
                  <Text weight="medium">{x.setting}:</Text>{" "}
                  {Object.entries(x.groups)
                    .map(([value, who]) => `${value} (${who.join(", ")})`)
                    .join("  vs  ")}
                </Text>
              ))}
            </Flex>
          </Callout.Root>
        )}
      </Flex>
    </Card>
  );
}
