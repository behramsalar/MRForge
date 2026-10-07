import type { WorkspaceState } from "../api/types";
import { AnatomicalPage } from "./AnatomicalPage";
import { FullProcessingPage } from "./FullProcessingPage";
import { ComponentReviewPage } from "./ComponentReviewPage";
import { FunctionalPage } from "./FunctionalPage";
import { StagePage } from "./StagePage";

/** The kind of processing chosen in the sidebar tree: Pipelines (the default), or one single step. */
export function ProcessPage({ ws, tab, state }: { ws: string; tab?: string; state: WorkspaceState | null }) {
  if (tab === "func") return <FunctionalPage ws={ws} state={state} />;
  if (tab === "mni") {
    return (
      <StagePage
        ws={ws}
        state={state}
        stage="standard_space"
        title="Standard space"
        description="Moves a subject's functional runs into standard (MNI) space, using the cleaned data when there is any."
      />
    );
  }
  if (tab === "ica") return <ComponentReviewPage ws={ws} />;
  if (tab === "anat") return <AnatomicalPage ws={ws} state={state} />;
  return <FullProcessingPage ws={ws} state={state} />;
}
