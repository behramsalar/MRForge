import { Button, Dialog, Flex, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { call } from "../api/call";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";
import { ApiError } from "../api/call";

/** Pick a folder or ZIP on the computer running MRForge (inside the home folder). */
export function FolderPicker({
  open,
  onOpenChange,
  onPick,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (path: string, name: string) => void;
}) {
  const [path, setPath] = useState<string | undefined>(undefined);
  const listing = useQuery({
    queryKey: ["fs", path],
    enabled: open,
    queryFn: () => call(api.GET("/api/fs", { params: { query: { path } } })),
  });
  const here = listing.data?.path ?? "";
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="640px">
        <Dialog.Title>Choose the scanner files</Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          Pick the folder that holds the DICOM files (subfolders are included), or a ZIP file.
        </Dialog.Description>
        <Flex direction="column" gap={space.group} mt="3">
          <Flex align="center" gap={space.inline}>
            <Button
              variant="soft"
              size="1"
              disabled={!listing.data?.parent}
              onClick={() => setPath(listing.data?.parent ?? undefined)}
            >
              Up
            </Button>
            <Text size={type.help} color="gray" truncate>
              {here}
            </Text>
          </Flex>
          {listing.error && <ErrorCallout error={(listing.error as ApiError).body} />}
          <Flex direction="column" style={{ maxHeight: 320, overflowY: "auto" }}>
            {listing.data?.entries.length === 0 && (
              <Text size={type.help} color="gray">
                No folders or ZIP files here.
              </Text>
            )}
            {listing.data?.entries.map((e) => (
              <Button
                key={e.path}
                variant="ghost"
                color="gray"
                style={{ justifyContent: "flex-start" }}
                onClick={() => (e.kind === "dir" ? setPath(e.path) : (onPick(e.path, e.name), onOpenChange(false)))}
              >
                {e.name}{e.kind === "zip" ? " (ZIP file)" : ""}
              </Button>
            ))}
          </Flex>
        </Flex>
        <Flex justify="between" mt="4">
          <Dialog.Close>
            <Button variant="soft" color="gray">
              Cancel
            </Button>
          </Dialog.Close>
          <Button
            disabled={!here}
            onClick={() => {
              onPick(here, here.split("/").pop() ?? here);
              onOpenChange(false);
            }}
          >
            Use this folder
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
