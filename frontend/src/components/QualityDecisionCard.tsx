import { CheckIcon, Cross2Icon, EyeOpenIcon } from "@radix-ui/react-icons";
import { Badge, Button, Callout, Card, Dialog, Flex, Heading, Text, TextArea } from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ApiError, call } from "../api/call";
import type { Overview } from "../api/types";
import { when } from "../lib/labels";
import { space, type } from "../theme/tokens";
import { ErrorCallout } from "./ErrorCallout";

type Row = Overview["subjects"][number];
type Choice = "accept" | "review" | "exclude";

export const DECISION_LABEL: Record<Choice, string> = { accept: "Accepted", review: "To review", exclude: "Excluded" };
export const DECISION_COLOUR: Record<Choice, "green" | "amber" | "red"> = { accept: "green", review: "amber", exclude: "red" };

const QUICK: Record<Choice, string[]> = {
  accept: ["Checked: motion and registration look fine", "Checked the quality pictures"],
  review: ["Motion looks high; want a second opinion", "Registration looks off; look again"],
  exclude: ["Too much head motion", "Poor registration", "Scanner artefact", "Incomplete scan"],
};

const ICON = { accept: <CheckIcon />, review: <EyeOpenIcon />, exclude: <Cross2Icon /> };

/** The researcher's decision about a subject. MRForge only flags; the decision, with its reason,
 * is always the researcher's, and every earlier decision stays in the history. */
export function QualityDecisionCard({ ws, row }: { ws: string; row: Row }) {
  const client = useQueryClient();
  const [choice, setChoice] = useState<Choice | null>(null);
  const [reason, setReason] = useState("");
  const history = useQuery({
    queryKey: ["ws", ws, "qc-decision", row.label],
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/subjects/{label}/qc-decision", { params: { path: { ws_id: ws, label: row.label } } })),
  });
  const save = useMutation({
    mutationFn: (c: Choice) =>
      call(
        api.PUT("/api/workspaces/{ws_id}/subjects/{label}/qc-decision", {
          params: { path: { ws_id: ws, label: row.label } },
          body: { decision: c, reason },
        }),
      ),
    onSuccess: () => {
      setChoice(null);
      setReason("");
      void client.invalidateQueries({ queryKey: ["ws", ws] });
    },
  });
  const current = row.qc_decision as Choice | null;
  const entries = [...(history.data ?? [])].reverse();
  return (
    <Card size="2">
      <Flex direction="column" gap={space.group}>
        <Flex justify="between" align="center" wrap="wrap" gap={space.group}>
          <Heading as="h2" size={type.sectionTitle}>
            Quality decision
          </Heading>
          {current && (
            <Badge color={DECISION_COLOUR[current]} variant="soft" size="2">
              {DECISION_LABEL[current]}
            </Badge>
          )}
        </Flex>
        {row.motion_flag && (
          <Callout.Root color="amber" size="1">
            <Callout.Text>{row.motion_flag}. This is a prompt to look at the plots, not a verdict.</Callout.Text>
          </Callout.Root>
        )}
        {current && (
          <Text size={type.help} color="gray">
            Reason: {row.qc_reason}
          </Text>
        )}
        <Text size={type.help} color="gray">
          Look at the quality checks in the Results tab, then decide. Every decision needs a reason and can be changed later.
        </Text>
        <Flex gap="2" wrap="wrap">
          {(["accept", "review", "exclude"] as Choice[]).map((c) => (
            <Button key={c} variant={current === c ? "solid" : "soft"} color={DECISION_COLOUR[c]} onClick={() => setChoice(c)}>
              {ICON[c]} {c === "accept" ? "Accept" : c === "review" ? "Mark for review" : "Exclude"}
            </Button>
          ))}
        </Flex>
        {entries.length > 0 && (
          <details>
            <summary>
              <Text size={type.help}>History ({entries.length})</Text>
            </summary>
            <Flex direction="column" gap="2" mt="2">
              {entries.map((e, i) => (
                <Flex key={i} direction="column">
                  <Text size={type.help}>
                    <Badge color={DECISION_COLOUR[e.decision]} variant="soft">
                      {DECISION_LABEL[e.decision]}
                    </Badge>{" "}
                    {e.reason}
                  </Text>
                  <Text size={type.caption} color="gray">
                    {when(e.when)}
                    {e.who ? ` · ${e.who}` : ""}
                  </Text>
                </Flex>
              ))}
            </Flex>
          </details>
        )}
      </Flex>
      <Dialog.Root open={choice !== null} onOpenChange={(o) => !o && setChoice(null)}>
        <Dialog.Content maxWidth="480px">
          <Dialog.Title>
            {choice === "accept" ? "Accept" : choice === "review" ? "Mark for review" : "Exclude"} {row.label}
          </Dialog.Title>
          <Dialog.Description size={type.help} color="gray">
            {choice === "exclude"
              ? "An excluded subject is left out of the analysis-ready folder and unticked in batches. You can change this later."
              : "Say why, in a few words. It is kept with your name and the date."}
          </Dialog.Description>
          <Flex direction="column" gap="2" mt="3">
            <Flex gap="1" wrap="wrap">
              {(choice ? QUICK[choice] : []).map((q) => (
                <Button key={q} size="1" variant="soft" color="gray" onClick={() => setReason(q)}>
                  {q}
                </Button>
              ))}
            </Flex>
            <TextArea placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason" autoFocus />
            {save.error && <ErrorCallout error={(save.error as ApiError).body} />}
          </Flex>
          <Flex justify="end" gap="2" mt="4">
            <Button variant="soft" color="gray" onClick={() => setChoice(null)}>
              Cancel
            </Button>
            <Button disabled={!reason.trim() || save.isPending} color={choice ? DECISION_COLOUR[choice] : undefined} onClick={() => choice && save.mutate(choice)}>
              Save decision
            </Button>
          </Flex>
        </Dialog.Content>
      </Dialog.Root>
    </Card>
  );
}
