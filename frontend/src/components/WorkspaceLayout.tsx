import { Badge, Box, Button, Flex, Heading, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";
import { useWorkspaceState } from "../api/hooks";
import { href } from "../lib/router";
import { layout, space } from "../theme/tokens";
import { ActivityPanel } from "./ActivityPanel";

const steps = [
  { page: "import", label: "1. Import" },
  { page: "anat", label: "2. Anatomical" },
  { page: "func", label: "3. Functional" },
  { page: "view", label: "4. View" },
] as const;

/** Header with the linear flow (Import, Anatomical, View) and the live activity panel. */
export function WorkspaceLayout({
  ws,
  page,
  children,
}: {
  ws: string;
  page: string;
  children: (state: ReturnType<typeof useWorkspaceState>["state"]) => ReactNode;
}) {
  const { state, connected } = useWorkspaceState(ws);
  return (
    <Box>
      <Box style={{ borderBottom: "1px solid var(--gray-5)" }}>
        <Flex
          align="center"
          justify="between"
          px={space.page}
          py="3"
          maxWidth={layout.contentWidth}
          mx="auto"
          gap={space.group}
          wrap="wrap"
        >
          <Flex align="center" gap={space.group}>
            <Button asChild variant="ghost" color="gray" size="2">
              <a href="#/">MRForge</a>
            </Button>
            <Text color="gray">/</Text>
            <Heading size="4">{ws}</Heading>
            {!connected && (
              <Badge color="orange" variant="soft">
                Reconnecting…
              </Badge>
            )}
          </Flex>
          <Flex gap={space.inline}>
            {steps.map((s) => (
              <Button key={s.page} asChild variant={page === s.page ? "solid" : "soft"} size="2">
                <a href={href(ws, s.page)}>{s.label}</a>
              </Button>
            ))}
          </Flex>
        </Flex>
      </Box>
      <Flex direction="column" gap={space.section} p={space.page} maxWidth={layout.contentWidth} mx="auto">
        <ActivityPanel ws={ws} state={state} />
        {children(state)}
      </Flex>
    </Box>
  );
}
