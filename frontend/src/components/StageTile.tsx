import { ArrowTopRightIcon, CheckIcon, MixerHorizontalIcon } from "@radix-ui/react-icons";
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
  description,
  params,
  status,
  hasSettings,
  changed,
  onSettings,
  pageHref,
}: {
  label: string;
  plan?: StagePlan;
  enabled: boolean;
  onToggle: (on: boolean) => void;
  description: string;
  params: { name: string; value: string }[];
  status?: string;
  hasSettings: boolean;
  changed: boolean;
  onSettings: () => void;
  pageHref?: string; // the stage's own page: run it alone and see its results
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
        <span className="tile-desc" title={description}>
          {blocked ? `Not possible: ${plan?.reason}` : description}
        </span>
        <span className="tile-params" aria-label="Chosen settings">
          {params.slice(0, 6).map((x) => (
            <span key={`${x.name}:${x.value}`} className="tile-param" title={`${x.name}: ${x.value}`}>
              <span className="tile-pn">{x.name}</span>
              <span className="tile-pv">{x.value}</span>
            </span>
          ))}
          {params.length === 0 && <span className="tile-param tile-pn">No settings</span>}
        </span>
        {status && !blocked && (
          <Badge color="green" variant="soft" size="1" className="tile-badge">
            {status}
          </Badge>
        )}
      </button>
      {pageHref && (
        <Tooltip content={`Open the ${label} page: run this stage alone and see its results`}>
          <IconButton className="tile-page" size="1" variant="ghost" color="gray" asChild>
            <a href={pageHref} aria-label={`Open the ${label} page`}>
              <ArrowTopRightIcon />
            </a>
          </IconButton>
        </Tooltip>
      )}
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
