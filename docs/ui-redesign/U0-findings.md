# U0: what the existing API already gives (checked 2026-11-10, read from code and the running app)

Conclusion: **the Overview, "Your move", pipeline map, journey cards and sidebar badges need no backend change.** Only the items marked "needs backend" below would.

| UI idea | Source that exists today | Backend change? |
|---|---|---|
| Journey cards (Import / Process / Check quality / Results) with counts | `GET /workspaces/{ws}/overview`: `subjects_total, processed, failed, needs_review, excluded, running, stages[] (done/total per stage)` | No |
| "Your move" list (things waiting for the researcher) | `overview.review[]` (subject, what, since, page: labels to give), failed/stopped subjects (`subjects[].stages[].state`), `running_now`, `recent` | No. Undecided QC is derivable: processed subjects with `qc_decision == null` |
| Pipeline map (subject x stage grid) | `overview.subjects[].stages[]`: id, label, state (none, unavailable, waiting, running, review, partial, done, failed, stopped), detail. Stages: import, anatomical, preprocessing, artifact_rejection, standard_space, connectivity, diffusion | No |
| Sidebar badges | Counts from the same overview | No |
| Live memory in the sidebar | `GET /resources` -> `machine: cores, ram_gb, free_ram_gb, jobs_running` and the policy (max subjects, threads) | **No** for memory and slots (earlier plan said "needs backend"). **Needs backend** only for live CPU load (small: add `psutil.cpu_percent` to `Machine`) |
| Quality grid across subjects | `GET /subjects/{label}/qc` is per subject (pictures + metrics) | Works with lazy loading (one request per visible card). A single list endpoint would be better for 100 subjects (small) |
| Subject page, Results, report | existing | No |
| Activity popover | `overview.running_now`, `recent`, operations | No |
| Command palette (subjects, pages, actions) | subjects list + nav | No |
| Methods text | not built | **Needs backend** (generator, later) |

Server on port 8000 is the user's and was only read. Checks use a scratch copy of the `nifti` workspace (one subject) and a second server on port 8100; 20+ fake subjects are made in U3 when the Overview needs them.
