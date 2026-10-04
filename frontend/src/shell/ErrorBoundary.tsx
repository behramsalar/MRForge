import { Button, Callout, Flex, Text } from "@radix-ui/themes";
import { Component, type ReactNode } from "react";

/** If a page breaks, say so in plain words and offer a way out, instead of a blank screen. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.failed && prev.resetKey !== this.props.resetKey) this.setState({ failed: false });
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <Callout.Root color="red" role="alert">
        <Flex direction="column" gap="2">
          <Text weight="bold">Something went wrong on this page.</Text>
          <Text size="2">
            Your data is safe. Reload the page to try again; if it keeps happening, tell whoever looks after MRForge
            what you were doing.
          </Text>
          <Flex>
            <Button onClick={() => location.reload()}>Reload the page</Button>
          </Flex>
        </Flex>
      </Callout.Root>
    );
  }
}
