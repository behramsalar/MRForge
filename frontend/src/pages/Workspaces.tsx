import { Button, Callout, Card, Dialog, Flex, Grid, Heading, Text, TextField } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { useWorkspaces } from "../api/hooks";
import { ErrorCallout } from "../components/ErrorCallout";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

export function Workspaces() {
  const list = useWorkspaces();
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [open, setOpen] = useState(false);
  const create = useMutation({
    mutationFn: () => call(api.POST("/api/workspaces", { body: { name } })),
    onSuccess: (made) => {
      client.invalidateQueries({ queryKey: ["workspaces"] });
      location.hash = href(made.id, "import");
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

      {list.error && <ErrorCallout error={(list.error as ApiError).body} />}
      {list.data?.length === 0 && (
        <Callout.Root>
          <Callout.Text>No workspaces yet. Create one to import your first scan.</Callout.Text>
        </Callout.Root>
      )}
      <Grid columns={{ initial: "1", sm: "2", md: "3" }} gap={space.group}>
        {list.data?.map((w) => (
          <Card key={w.id} asChild size="3">
            <a href={href(w.id, "import")} style={{ textDecoration: "none" }}>
              <Flex direction="column" gap="1">
                <Text weight="bold" size={type.body}>
                  {w.name}
                </Text>
                <Text color="gray" size={type.help}>
                  {w.subjects} {w.subjects === 1 ? "subject" : "subjects"} · {w.imports}{" "}
                  {w.imports === 1 ? "import" : "imports"}
                </Text>
              </Flex>
            </a>
          </Card>
        ))}
      </Grid>
    </Flex>
  );
}
