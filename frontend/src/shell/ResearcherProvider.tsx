import { Button, Dialog, Flex, Text, TextField } from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, RESEARCHER_KEY } from "../api/client";
import { ApiError, call } from "../api/call";
import type { ResearcherInfo } from "../api/types";
import { ErrorCallout } from "../components/ErrorCallout";
import { parse } from "../lib/router";
import { space, type } from "../theme/tokens";
import { pageLabel } from "./nav";

export type LastWork = { hash: string; label: string };

type Ctx = {
  researcher: ResearcherInfo | null;
  researchers: ResearcherInfo[];
  lastWork: LastWork | null; // where this researcher stopped last time (before this visit)
  openPicker: () => void;
};
const ResearcherContext = createContext<Ctx | null>(null);

export function useResearcher(): Ctx {
  const ctx = useContext(ResearcherContext);
  if (!ctx) throw new Error("useResearcher needs a ResearcherProvider");
  return ctx;
}

const lastKey = (id: number) => `mrforge-last-${id}`;

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* not remembered */
  }
}

// "Not now" lasts for this visit only (the tab), so the question comes back next time.
function skippedThisVisit(): boolean {
  try {
    return sessionStorage.getItem("mrforge-skip-picker") === "1";
  } catch {
    return false;
  }
}
function skipForThisVisit() {
  try {
    sessionStorage.setItem("mrforge-skip-picker", "1");
  } catch {
    /* asked again on reload */
  }
}

function describe(hash: string): string {
  const r = parse(hash);
  return r.workspace ? `${r.workspace} · ${pageLabel(r.page)}` : pageLabel(r.page);
}

/**
 * Light researcher profiles: a name picked on a shared computer, so people can follow and
 * resume their own work. NOT a login and not protection: anyone can pick any name.
 */
export function ResearcherProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["researchers"],
    queryFn: () => call(api.GET("/api/researchers")),
  });
  const [id, setId] = useState<number | null>(() => {
    const raw = read(RESEARCHER_KEY);
    return raw && /^\d+$/.test(raw) ? Number(raw) : null;
  });
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState(false);
  const researchers = list.data ?? [];
  const researcher = researchers.find((r) => r.id === id) ?? null;

  // Ask once per visit when nobody is chosen yet (or the chosen profile no longer exists).
  useEffect(() => {
    if (list.isSuccess && !researcher && !asked && !skippedThisVisit()) {
      setOpen(true);
      setAsked(true);
    }
  }, [list.isSuccess, researcher, asked]);

  // Where this researcher stopped last time: read once when they are chosen, then keep
  // writing the current place so the next visit can offer it.
  const [lastWork, setLastWork] = useState<LastWork | null>(null);
  useEffect(() => {
    if (!researcher) {
      setLastWork(null);
      return;
    }
    const stored = read(lastKey(researcher.id));
    setLastWork(stored && stored !== location.hash ? { hash: stored, label: describe(stored) } : null);
    const note = () => {
      if (parse(location.hash).workspace) write(lastKey(researcher.id), location.hash);
    };
    note();
    addEventListener("hashchange", note);
    return () => removeEventListener("hashchange", note);
  }, [researcher?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (r: ResearcherInfo) => {
    write(RESEARCHER_KEY, String(r.id));
    setId(r.id);
    setOpen(false);
    client.invalidateQueries();
  };
  const value = useMemo<Ctx>(
    () => ({ researcher, researchers, lastWork, openPicker: () => setOpen(true) }),
    [researcher, researchers, lastWork],
  );
  return (
    <ResearcherContext.Provider value={value}>
      {children}
      <Picker open={open} onOpenChange={setOpen} researchers={researchers} onChoose={choose} />
    </ResearcherContext.Provider>
  );
}

function Picker({
  open,
  onOpenChange,
  researchers,
  onChoose,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  researchers: ResearcherInfo[];
  onChoose: (r: ResearcherInfo) => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const add = useMutation({
    mutationFn: () => call(api.POST("/api/researchers", { body: { name } })),
    onSuccess: (r) => {
      client.invalidateQueries({ queryKey: ["researchers"] });
      setName("");
      onChoose(r);
    },
  });
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="460px">
        <Dialog.Title>Who is working?</Dialog.Title>
        <Dialog.Description size={type.help} color="gray">
          Pick your name so MRForge can show your recent work and note who started what. This is not
          a login: it only keeps people apart on a shared computer and protects nothing.
        </Dialog.Description>
        <Flex direction="column" gap={space.inline} mt="4">
          {researchers.map((r) => (
            <Button key={r.id} variant="soft" color="gray" style={{ justifyContent: "flex-start" }} onClick={() => onChoose(r)}>
              {r.name}
            </Button>
          ))}
          <Text size={type.help} weight="medium" mt="2">
            {researchers.length ? "Not on the list?" : "Add your name"}
          </Text>
          <Flex gap={space.inline}>
            <TextField.Root
              style={{ flex: 1 }}
              placeholder="Jane Smith"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && name.trim() && add.mutate()}
            />
            <Button disabled={!name.trim() || add.isPending} onClick={() => add.mutate()}>
              Add and continue
            </Button>
          </Flex>
          {add.error && <ErrorCallout error={(add.error as ApiError).body} />}
        </Flex>
        <Flex justify="end" mt="4">
          <Button
            variant="ghost"
            color="gray"
            onClick={() => {
              skipForThisVisit();
              onOpenChange(false);
            }}
          >
            Not now
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
