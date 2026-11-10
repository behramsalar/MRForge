/** The outcomes a researcher can ask for on the Process page. A goal is a set of stages (the
 * stage ids of the confirmation dialog); the dialog still shows exactly what will run and lets
 * the researcher change it. ``stages: null`` means "the server's own defaults". Nothing here
 * decides anything scientific: the stage sets only name stages that already exist. */
export type Goal = {
  id: string;
  title: string;
  text: string;
  stages: string[] | null; // dialog stage ids; null = defaults chosen by the server
  route: string[]; // stage ids drawn on the route map, in order
  optionalArtifact: boolean; // offer "include artifact rejection"
};

/** Dialog stage id -> the id the overview uses for the same stage. */
export const OVERVIEW_ID: Record<string, string> = {
  anatomical: "anatomical",
  functional: "preprocessing",
  artifact_rejection: "artifact_rejection",
  standard_space: "standard_space",
  connectivity: "connectivity",
  diffusion: "diffusion",
};

export const STAGE_NAME: Record<string, string> = {
  anatomical: "Anatomy",
  functional: "Functional",
  artifact_rejection: "Artifact rejection",
  standard_space: "Standard space",
  connectivity: "Connectivity",
  diffusion: "Diffusion",
};

export const GOALS: Goal[] = [
  {
    id: "full",
    title: "Full processing",
    text: "The recommended set: every stage the app proposes by default.",
    stages: null,
    route: ["anatomical", "functional", "artifact_rejection", "standard_space"],
    optionalArtifact: false,
  },
  {
    id: "prepare",
    title: "Clean the scans",
    text: "Anatomical and functional preprocessing, in each subject's own space.",
    stages: ["anatomical", "functional"],
    route: ["anatomical", "functional"],
    optionalArtifact: false,
  },
  {
    id: "mni",
    title: "Analysis-ready in standard space",
    text: "Everything up to the functional data in MNI space.",
    stages: ["anatomical", "functional", "standard_space"],
    route: ["anatomical", "functional", "artifact_rejection", "standard_space"],
    optionalArtifact: true,
  },
  {
    id: "connectivity",
    title: "Connectivity matrices",
    text: "Region time series and correlation matrices for the chosen atlases.",
    stages: ["anatomical", "functional", "standard_space", "connectivity"],
    route: ["anatomical", "functional", "artifact_rejection", "standard_space", "connectivity"],
    optionalArtifact: true,
  },
  {
    id: "diffusion",
    title: "Diffusion (ALPS index)",
    text: "Corrects the diffusion scan and computes the ALPS index. Needs no other stage.",
    stages: ["diffusion"],
    route: ["diffusion"],
    optionalArtifact: false,
  },
];

/** The stages to tick when the dialog opens for this goal, or undefined for the server defaults. */
export function goalStages(g: Goal, withArtifact: boolean): string[] | undefined {
  if (!g.stages) return undefined;
  return withArtifact && g.optionalArtifact ? [...g.stages, "artifact_rejection"] : g.stages;
}
