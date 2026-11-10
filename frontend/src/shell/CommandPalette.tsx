import { MagnifyingGlassIcon } from "@radix-ui/react-icons";
import { Dialog, Flex, Text, TextField } from "@radix-ui/themes";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSubjects } from "../api/hooks";
import { buildEntries, filterEntries, type Entry } from "../lib/palette";
import { WORKSPACE_NAV, STAGE_PAGES } from "./nav";
import { useResearcher } from "./ResearcherProvider";
import { useAppTheme } from "./ThemeProvider";

/** Cmd/Ctrl+K: jump to a page or a subject, or do a small action, without the mouse. */
export function CommandPalette({
  ws,
  open,
  onOpenChange,
  onShortcuts,
}: {
  ws: string | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onShortcuts: () => void;
}) {
  const subjects = useSubjects(ws ?? "");
  const { toggle } = useAppTheme();
  const { openPicker } = useResearcher();
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const entries = useMemo(
    () => buildEntries(ws, WORKSPACE_NAV, ws ? (subjects.data ?? []).map((s) => s.label) : [], STAGE_PAGES),
    [ws, subjects.data],
  );
  const shown = useMemo(() => filterEntries(entries, query), [entries, query]);
  useEffect(() => {
    if (open) {
      setQuery("");
      setIndex(0);
    }
  }, [open]);
  useEffect(() => setIndex(0), [query]);
  useEffect(() => {
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [index]);

  const run = (e: Entry | undefined) => {
    if (!e) return;
    onOpenChange(false);
    if (e.to) location.hash = e.to;
    else if (e.action === "theme") toggle();
    else if (e.action === "researcher") openPicker();
    else if (e.action === "workspaces") location.hash = "#/";
    else if (e.action === "shortcuts") onShortcuts();
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="520px" style={{ padding: 0 }} aria-describedby={undefined}>
        <Dialog.Title className="sr-only">Jump to</Dialog.Title>
        <Flex direction="column">
          <div style={{ padding: "var(--space-3)", borderBottom: "1px solid var(--gray-5)" }}>
            <TextField.Root
              autoFocus
              placeholder="Jump to a page, subject or action"
              aria-label="Jump to a page, subject or action"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setIndex((i) => Math.min(i + 1, shown.length - 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setIndex((i) => Math.max(i - 1, 0));
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  run(shown[index]);
                }
              }}
            >
              <TextField.Slot>
                <MagnifyingGlassIcon />
              </TextField.Slot>
            </TextField.Root>
          </div>
          <div ref={listRef} role="listbox" className="palette-list">
            {shown.length === 0 && (
              <Text size="2" color="gray" style={{ padding: "var(--space-3)" }}>
                Nothing matches. Try a subject name or a page name.
              </Text>
            )}
            {shown.map((e, i) => (
              <div key={e.id}>
                {(i === 0 || shown[i - 1].group !== e.group) && <div className="palette-group">{e.group}</div>}
                <div
                  role="option"
                  aria-selected={i === index}
                  className="palette-item"
                  onMouseMove={() => setIndex(i)}
                  onClick={() => run(e)}
                >
                  <span>{e.label}</span>
                  {e.hint && <span className="palette-hint">{e.hint}</span>}
                </div>
              </div>
            ))}
          </div>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
