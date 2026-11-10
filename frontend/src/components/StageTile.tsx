import { CheckIcon, MixerHorizontalIcon } from "@radix-ui/react-icons";
import { Badge, IconButton, Tooltip } from "@radix-ui/themes";
import type { StagePlan } from "../api/types";
import "./overview.css";

/** One stage as a tile: click it to include or leave it out (filled = included); the gear opens
 * its settings. The tile says in one short line what it will do and, once subjects are
 * ticked, what is already done or impossible. */
export function StageTile({
  label,
  plan,
  enabled,
  onToggle,
  summary,
  status,
  hasSettings,
  changed,
  onSettings,
}: {
  label: string;
  plan?: StagePlan;
  enabled: boolean;
  onToggle: (on: boolean) => void;
  summary: string;
  status?: string;
  hasSettings: boolean;
  changed: boolean;
  onSettings: () => void;
}) {
  const blocked = !!plan && !plan.can_run;
  const on = enabled && !blocked;
  return (
    <div className="tile" data-on={on} data-blocked={blocked}>
      <button type="button" className="tile-main" aria-pressed={on} disabled={blocked} onClick={() => onToggle(!on)}>
        <span className="tile-check" aria-hidden>
          {on && <CheckIcon />}
        </span>
        <span className="tile-name">{label}</span>
        <span className="tile-sum" title={blocked ? undefined : summary}>
          {blocked ? `Not possible: ${plan?.reason}` : summary}
        </span>
        {status && !blocked && (
          <Badge color="green" variant="soft" size="1" className="tile-badge">
            {status}
          </Badge>
        )}
      </button>
      {hasSettings && (
        <Tooltip content={changed ? "Settings (changed)" : "Settings"}>
          <IconButton className="tile-gear" size="1" variant="ghost" color="gray" onClick={onSettings} aria-label={`Settings for ${label}`}>
            <MixerHorizontalIcon />
            {changed && <span className="tile-dot" aria-label="changed" />}
          </IconButton>
        </Tooltip>
      )}
    </div>
  );
}
