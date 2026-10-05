import { CheckIcon } from "@radix-ui/react-icons";
import { Card, Flex, Heading, Progress, Text } from "@radix-ui/themes";
import type { Overview } from "../api/types";
import { space, type } from "../theme/tokens";

/** The stages in order with how many subjects have finished each. */
export function PipelineStepper({ stages }: { stages: Overview["stages"] }) {
  return (
    <Card size="3">
      <Flex direction="column" gap={space.group}>
        <Heading as="h2" size={type.sectionTitle}>Processing pipeline</Heading>
        <Flex gap={space.group} wrap="wrap">
          {stages.map((st, i) => {
            const finished = st.total > 0 && st.done === st.total;
            const pct = st.total ? Math.round((100 * st.done) / st.total) : 0;
            return (
              <Flex key={st.id} direction="column" gap="2" style={{ flex: "1 1 160px", minWidth: 140 }}>
                <Flex align="center" gap={space.inline}>
                  <Flex
                    align="center"
                    justify="center"
                    style={{
                      width: 28,
                      height: 28,
                      borderRadius: "50%",
                      background: finished ? "var(--green-9)" : st.done > 0 ? "var(--accent-a5)" : "var(--gray-a4)",
                      color: finished ? "white" : st.done > 0 ? "var(--accent-11)" : "var(--gray-11)",
                      fontSize: "var(--font-size-1)",
                      fontWeight: 600,
                    }}
                  >
                    {finished ? <CheckIcon /> : i + 1}
                  </Flex>
                  <Text weight="bold" size={type.body}>
                    {st.label}
                  </Text>
                </Flex>
                <Progress value={pct} size="1" color={finished ? "green" : "orange"} aria-label={`${st.label} progress`} />
                <Text size={type.caption} color="gray">
                  {st.total === 0 ? "Nothing to do yet" : `${st.done} of ${st.total} ${st.total === 1 ? "subject" : "subjects"}`}
                </Text>
              </Flex>
            );
          })}
        </Flex>
      </Flex>
    </Card>
  );
}
