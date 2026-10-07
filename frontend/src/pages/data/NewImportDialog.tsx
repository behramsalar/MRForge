import { Button, Code, Dialog, Flex, Text, TextField } from "@radix-ui/themes";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { ApiError, call } from "../../api/call";
import { ErrorCallout } from "../../components/ErrorCallout";
import { FolderPicker } from "../../components/FolderPicker";
import { space, type } from "../../theme/tokens";

/** Choose the scanner files and read them. The series table then appears for confirmation. */
export function NewImportDialog({
  ws,
  disabled,
  onStarted,
}: {
  ws: string;
  disabled: boolean;
  onStarted: (operationId: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [picker, setPicker] = useState(false);
  const [source, setSource] = useState<{ path: string; name: string } | null>(null);
  const [subject, setSubject] = useState("");
  const scan = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/imports/scan", {
          params: { path: { ws_id: ws } },
          body: { source: source!.path, subject: subject.trim() || null },
        }),
      ),
    onSuccess: (r) => {
      onStarted(r.operation_id);
      setOpen(false);
      setSource(null);
      setSubject("");
    },
  });
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger>
        <Button size="3" disabled={disabled}>
          Import scans
        </Button>
      </Dialog.Trigger>
      <Dialog.Content maxWidth="520px">
        <Dialog.Title>Import scanner files</Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          MRForge reads the files, tells you what it found and asks only about what it cannot decide
          itself. Your original files are copied into the workspace and never changed.
        </Dialog.Description>
        <Flex direction="column" gap={space.group} mt="4">
          <Flex gap={space.group} align="center" wrap="wrap">
            <Button variant="soft" onClick={() => setPicker(true)}>
              {source ? "Choose another folder" : "Choose folder or archive"}
            </Button>
            {source && <Code>{source.name}</Code>}
          </Flex>
          <FolderPicker open={picker} onOpenChange={setPicker} onPick={(path, name) => setSource({ path, name })} />
          <Flex direction="column" gap="1">
            <Text size={type.help} weight="medium">
              Subject label (optional)
            </Text>
            <TextField.Root placeholder="next free, e.g. sub-002" value={subject} onChange={(e) => setSubject(e.target.value)} />
          </Flex>
          {scan.error && <ErrorCallout error={(scan.error as ApiError).body} />}
        </Flex>
        <Flex justify="end" gap={space.group} mt="4">
          <Dialog.Close>
            <Button variant="soft" color="gray">
              Cancel
            </Button>
          </Dialog.Close>
          <Button disabled={!source || scan.isPending} onClick={() => scan.mutate()}>
            Read scanner files
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
