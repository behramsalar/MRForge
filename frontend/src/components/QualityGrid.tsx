import { Badge, Flex, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { call } from "../api/call";
import type { Overview } from "../api/types";
import { findQc, thumbnailOf, type CheckId } from "../lib/qualityReview";
import { type } from "../theme/tokens";
import { DECISION_COLOUR, DECISION_LABEL } from "./QualityDecisionCard";
import "./overview.css";

type Row = Overview["subjects"][number];

/** The report of one subject, fetched on demand and kept (the inspector reuses it). */
export function useSubjectReport(ws: string, label: string, enabled = true) {
  return useQuery({
    queryKey: ["ws", ws, "report", label],
    enabled,
    staleTime: 60_000,
    queryFn: () => call(api.GET("/api/workspaces/{ws_id}/subjects/{label}/report", { params: { path: { ws_id: ws, label } } })),
  });
}

function useSeen() {
  const ref = useRef<HTMLButtonElement>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    if (typeof IntersectionObserver === "undefined") return setSeen(true);
    const io = new IntersectionObserver((e) => e.some((x) => x.isIntersecting) && setSeen(true), { rootMargin: "200px" });
    io.observe(el);
    return () => io.disconnect();
  }, [seen]);
  return { ref, seen };
}

function Tile({ ws, row, check, onOpen }: { ws: string; row: Row; check: CheckId; onOpen: (label: string) => void }) {
  const { ref, seen } = useSeen();
  const report = useSubjectReport(ws, row.label, seen);
  const found = findQc(report.data, check);
  const picture = found[0] ? thumbnailOf(found[0].qc) : null;
  const decision = row.qc_decision as keyof typeof DECISION_LABEL | null;
  return (
    <button type="button" ref={ref} className="qg-tile" data-decision={decision ?? ""} onClick={() => onOpen(row.label)} aria-label={`Open ${row.label}`}>
      <span className="qg-pic">
        {picture ? (
          <img src={`/api/workspaces/${ws}/file/${picture}`} alt={`${row.label}: ${found[0].qc.name}`} loading="lazy" />
        ) : (
          <Text size={type.caption} color="gray">
            {!seen || report.isLoading ? "Loading…" : "No picture for this check"}
          </Text>
        )}
      </span>
      <Flex justify="between" align="center" gap="2" className="qg-foot">
        <Text size={type.help} weight="medium">
          {row.label}
        </Text>
        <Flex gap="1" align="center">
          {row.motion_flag && (
            <Badge color="amber" variant="soft" size="1" title={row.motion_flag}>
              motion
            </Badge>
          )}
          {decision && (
            <Badge color={DECISION_COLOUR[decision]} variant="soft" size="1" title={row.qc_reason ?? undefined}>
              {DECISION_LABEL[decision]}
            </Badge>
          )}
        </Flex>
      </Flex>
    </button>
  );
}

/** One picture per subject for the chosen check, side by side, so an odd one stands out.
 * Pictures load only when they scroll into view. Click a tile to inspect and decide. */
export function QualityGrid({ ws, subjects, check, onOpen }: { ws: string; subjects: Row[]; check: CheckId; onOpen: (label: string) => void }) {
  return (
    <div className="qg">
      {subjects.map((r) => (
        <Tile key={`${r.label}:${check}`} ws={ws} row={r} check={check} onOpen={onOpen} />
      ))}
    </div>
  );
}
