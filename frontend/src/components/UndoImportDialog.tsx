import { Button, Callout, Checkbox, Dialog, Flex, Text } from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import { humanSize } from "../lib/labels";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

/** Undo a whole import on purpose: say exactly what goes and what stays, ask for confirmation. */
export function UndoImportDialog({ ws, importId, subject }: { ws: string; importId: string; subject: string }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [sure, setSure] = useState(false);
  const plan = useQuery({
    queryKey: ["ws", ws, "undo-plan", importId],
    enabled: open,
    queryFn: () =>
      call(
        api.GET("/api/workspaces/{ws_id}/imports/{import_id}/undo-plan", {
          params: { path: { ws_id: ws, import_id: importId } },
        }),
      ),
  });
  const undo = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/imports/{import_id}/undo", {
          params: { path: { ws_id: ws, import_id: importId } },
        }),
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["ws", ws] });
      setOpen(false);
      setSure(false);
    },
  });
  const p = plan.data;
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setSure(false);
      }}
    >
      <Dialog.Trigger>
        <Button variant="soft" color="red">
          Undo import…
        </Button>
      </Dialog.Trigger>
      <Dialog.Content maxWidth="520px">
        <Dialog.Title>Undo the import of {subject}?</Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          This takes the imported images back out of the data folder so you can change your decisions (skip a
          series, rename a task) and import again.
        </Dialog.Description>
        <Flex direction="column" gap={space.group} mt="4">
          {plan.error && <ErrorCallout error={(plan.error as ApiError).body} />}
          {p && (
            <>
              <Text size={type.body}>
                Removed from the data folder: <b>{p.files} files</b> ({humanSize(p.size_bytes)}) of {p.series}{" "}
                {p.series === 1 ? "series" : "series"}.
              </Text>
              <Text size={type.help} color="gray">
                Kept: the converted copies in this workspace and your scanner files, so nothing is lost and
                importing again is quick.
              </Text>
              {p.only_copy > 0 && (
                <Callout.Root color="amber" size="1">
                  <Callout.Text>
                    {p.only_copy} {p.only_copy === 1 ? "image has" : "images have"} no other copy in this workspace
                    (they were copied from files you chose). Your original files are untouched, but you would
                    have to import them again.
                  </Callout.Text>
                </Callout.Root>
              )}
              {p.stale_steps.length > 0 && (
                <Callout.Root color="amber" size="1">
                  <Callout.Text>
                    Results already made from these images stay, but they will no longer be up to date:{" "}
                    {p.stale_steps.join(", ")}.
                  </Callout.Text>
                </Callout.Root>
              )}
              {p.problems.length > 0 && (
                <Callout.Root color="red" size="1">
                  <Callout.Text>
                    Some imported files were changed after the import, so nothing can be removed: {p.problems.slice(0, 3).join(", ")}.
                  </Callout.Text>
                </Callout.Root>
              )}
              <Text as="label" size={type.help}>
                <Flex gap={space.inline} align="center">
                  <Checkbox checked={sure} onCheckedChange={(v) => setSure(v === true)} />
                  I understand that the imported images will be removed from the data folder.
                </Flex>
              </Text>
            </>
          )}
          {undo.error && <ErrorCallout error={(undo.error as ApiError).body} />}
        </Flex>
        <Flex justify="end" gap={space.group} mt="4">
          <Dialog.Close>
            <Button variant="soft" color="gray">
              Cancel
            </Button>
          </Dialog.Close>
          <Button
            color="red"
            disabled={!sure || !p || p.problems.length > 0 || undo.isPending}
            onClick={() => undo.mutate()}
          >
            Undo import
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
