import { LayersIcon, PersonIcon } from "@radix-ui/react-icons";
import { Badge, Button, Callout, Card, Dialog, Flex, Grid, Heading, SegmentedControl, Text, TextField } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useWorkspaces } from "../api/hooks";
import { ErrorCallout } from "../components/ErrorCallout";
import { href } from "../lib/router";
import { useResearcher } from "../shell/ResearcherProvider";
import { space, type } from "../theme/tokens";

export function Workspaces() {
  const list = useWorkspaces();
  const { researcher, lastWork } = useResearcher();
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [only, setOnly] = useState<"all" | "mine">("all");
  const [open, setOpen] = useState(false);
  const create = useMutation({
    mutationFn: () => call(api.POST("/api/workspaces", { body: { name } })),
    onSuccess: (made) => {
      client.invalidateQueries({ queryKey: ["workspaces"] });
      location.hash = href(made.id, "dashboard");
    },
  });
  return (
    <Flex direction="column" gap={space.section}>
      <Flex justify="between" align="end">
        <Flex direction="column" gap="1">
          <Heading size={type.pageTitle}>MRForge</Heading>
          <Text color="gray" size={type.body}>
            A workspace holds one study: its scans, results and notes.
          </Text>
        </Flex>
        <Dialog.Root open={open} onOpenChange={setOpen}>
          <Dialog.Trigger>
            <Button size="3">New workspace</Button>
          </Dialog.Trigger>
          <Dialog.Content maxWidth="420px">
            <Dialog.Title>New workspace</Dialog.Title>
            <Dialog.Description size={type.help} color="gray">
              Give it a name you will recognise, for example the study or the person.
            </Dialog.Description>
            <TextField.Root
              mt="3"
              placeholder="e.g. Pilot study"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && name.trim() && create.mutate()}
              autoFocus
            />
            {create.error && (
              <Flex mt="3">
                <ErrorCallout error={(create.error as ApiError).body} />
              </Flex>
            )}
            <Flex justify="end" gap={space.group} mt="4">
              <Dialog.Close>
                <Button variant="soft" color="gray">
                  Cancel
                </Button>
              </Dialog.Close>
              <Button disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
                Create
              </Button>
            </Flex>
          </Dialog.Content>
        </Dialog.Root>
      </Flex>

      {researcher && lastWork && (
        <Card size="3">
          <Flex justify="between" align="center" gap={space.group} wrap="wrap">
            <Flex direction="column">
              <Text weight="bold" size={type.body}>
                Welcome back, {researcher.name}
              </Text>
              <Text color="gray" size={type.help}>
                You were last in {lastWork.label}.
              </Text>
            </Flex>
            <Button asChild>
              <a href={lastWork.hash}>Continue where you left off</a>
            </Button>
          </Flex>
        </Card>
      )}
      {list.error && <ErrorCallout error={(list.error as ApiError).body} />}
      {list.data?.length === 0 && (
        <Callout.Root>
          <Callout.Text>No workspaces yet. Create one to import your first scan.</Callout.Text>
        </Callout.Root>
      )}
      {researcher && (list.data?.length ?? 0) > 0 && (
        <SegmentedControl.Root value={only} onValueChange={(v) => setOnly(v as "all" | "mine")} style={{ alignSelf: "flex-start" }}>
          <SegmentedControl.Item value="all">All workspaces</SegmentedControl.Item>
          <SegmentedControl.Item value="mine">Created by me</SegmentedControl.Item>
        </SegmentedControl.Root>
      )}
      {only === "mine" && list.data && !list.data.some((w) => w.created_by === researcher?.name) && (
        <Callout.Root>
          <Callout.Text>You have not created a workspace yet.</Callout.Text>
        </Callout.Root>
      )}
      <Grid columns={{ initial: "1", sm: "2", md: "3" }} gap={space.group}>
        {list.data?.filter((w) => only === "all" || w.created_by === researcher?.name).map((w) => (
          <Card key={w.id} asChild size="3">
            <a href={href(w.id, "dashboard")} style={{ textDecoration: "none" }}>
              <Flex direction="column" gap="2">
                <Flex align="center" gap={space.inline}>
                  <Flex
                    align="center"
                    justify="center"
                    aria-hidden
                    style={{ width: 32, height: 32, borderRadius: "var(--radius-3)", background: "var(--accent-a3)", color: "var(--accent-10)" }}
                  >
                    <LayersIcon />
                  </Flex>
                  <Text weight="bold" size={type.body}>
                    {w.name}
                  </Text>
                </Flex>
                <Text color="gray" size={type.help}>
                  {w.subjects} {w.subjects === 1 ? "subject" : "subjects"} · {w.imports}{" "}
                  {w.imports === 1 ? "import" : "imports"}
                </Text>
                {w.created_by && (
                  <Flex>
                    <Badge color={w.created_by === researcher?.name ? "orange" : "gray"} variant="soft" size="2">
                      <PersonIcon /> Created by {w.created_by}
                      {w.created_by === researcher?.name ? " (you)" : ""}
                    </Badge>
                  </Flex>
                )}
              </Flex>
            </a>
          </Card>
        ))}
      </Grid>
    </Flex>
  );
}
