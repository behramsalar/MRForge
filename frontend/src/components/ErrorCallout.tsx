import { Callout, Flex, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";
import type { ErrorBody } from "../api/types";
import { space, type } from "../theme/tokens";

/** Every failure: what happened, why it probably happened, what to do next. */
export function ErrorCallout({
  error,
  actions,
  color = "red",
}: {
  error: ErrorBody;
  actions?: ReactNode;
  color?: "red" | "orange";
}) {
  return (
    <Callout.Root color={color} role="alert">
      <Flex direction="column" gap={space.inline}>
        <Text weight="bold" size={type.body}>
          {error.message}
        </Text>
        {error.probable_cause && (
          <Text size={type.help}>
            <Text weight="medium">Why: </Text>
            {error.probable_cause}
          </Text>
        )}
        {error.suggested_action && (
          <Text size={type.help}>
            <Text weight="medium">What to do: </Text>
            {error.suggested_action}
          </Text>
        )}
        {actions && (
          <Flex gap={space.inline} mt="2" wrap="wrap">
            {actions}
          </Flex>
        )}
      </Flex>
    </Callout.Root>
  );
}
