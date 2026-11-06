import { Button, Callout, Code, Dialog, Flex, Text, TextField } from "@radix-ui/themes";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { ApiError, call } from "../../api/call";
import { ErrorCallout } from "../../components/ErrorCallout";
import { FolderPicker } from "../../components/FolderPicker";
import { space, type } from "../../theme/tokens";

/** Choose what to import (scanner files, archives, NIfTI files, a BIDS dataset) and read it.
 * The series table then appears for confirmation. */
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
  // What the chosen folder is, shown before anything is read ("Found 12 archives ...").
  const looked = useQuery({
    queryKey: ["inspect", ws, source?.path],
    enabled: !!source,
    retry: false,
    queryFn: () =>
      call(
        api.POST("/api/workspaces/{ws_id}/imports/inspect", {
          params: { path: { ws_id: ws } },
          body: { source: source!.path },
        }),
      ),
  });
  const kind = looked.data?.kind;
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
        <Dialog.Title>Import scans</Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          Choose a folder or archive with scanner files (DICOM), a folder with several archives,
          NIfTI files (one folder per subject), or an existing BIDS dataset. MRForge looks at what it is, tells
          you what it found and asks only about what it cannot decide itself. Your original files are copied
          into the workspace and never changed.
        </Dialog.Description>
        <Flex direction="column" gap={space.group} mt="4">
          <Flex gap={space.group} align="center" wrap="wrap">
            <Button variant="soft" onClick={() => setPicker(true)}>
              {source ? "Choose another folder" : "Choose folder or archive"}
            </Button>
            {source && <Code>{source.name}</Code>}
          </Flex>
          <FolderPicker open={picker} onOpenChange={setPicker} onPick={(path, name) => setSource({ path, name })} />
          {looked.data && (
            <Callout.Root color="gray" size="1">
              <Callout.Text>{looked.data.summary}</Callout.Text>
            </Callout.Root>
          )}
          {looked.error && <ErrorCallout error={(looked.error as ApiError).body} />}
          {(kind === "dicom" || kind === undefined) && (
          <Flex direction="column" gap="1">
            <Text size={type.help} weight="medium">
              Subject label (optional)
            </Text>
            <TextField.Root placeholder="next free, e.g. sub-002" value={subject} onChange={(e) => setSubject(e.target.value)} />
          </Flex>
          )}
          {scan.error && <ErrorCallout error={(scan.error as ApiError).body} />}
        </Flex>
        <Flex justify="end" gap={space.group} mt="4">
          <Dialog.Close>
            <Button variant="soft" color="gray">
              Cancel
            </Button>
          </Dialog.Close>
          <Button disabled={!looked.data || scan.isPending} onClick={() => scan.mutate()}>
            {kind === "bids" ? "Import dataset" : kind === "nifti" ? "Read NIfTI files" : kind === "archives" ? "Read all archives" : "Read scanner files"}
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
