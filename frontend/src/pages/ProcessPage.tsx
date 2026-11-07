import { Flex } from "@radix-ui/themes";
import { DiffusionResultsTable } from "../components/DiffusionResultsTable";
import { space } from "../theme/tokens";
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
  if (tab === "dwi") {
    return (
      <Flex direction="column" gap={space.section}>
        <StagePage
          ws={ws}
          state={state}
          stage="diffusion"
          title="Diffusion (ALPS)"
          description="Corrects a subject's diffusion scan, fits the diffusion tensor and computes the ALPS index (diffusion along perivascular spaces). It does not need the anatomical or functional stages."
          hint="Choose a subject with a diffusion scan."
        />
        <DiffusionResultsTable ws={ws} />
      </Flex>
    );
  }
  if (tab === "ica") return <ComponentReviewPage ws={ws} />;
  if (tab === "anat") return <AnatomicalPage ws={ws} state={state} />;
  return <FullProcessingPage ws={ws} state={state} />;
}
