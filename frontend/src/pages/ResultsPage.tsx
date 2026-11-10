import { Flex } from "@radix-ui/themes";
import { ConnectivityMatrixView } from "../components/ConnectivityMatrixView";
import { ConnectivityResultsTable } from "../components/ConnectivityResultsTable";
import { DiffusionResultsTable } from "../components/DiffusionResultsTable";
import { PageHeader } from "../components/ui/Layout";
import { space } from "../theme/tokens";

/** Results of the analyses, one tab per kind (the sidebar lists them). */
export function ResultsPage({ ws, tab }: { ws: string; tab?: string }) {
  if (tab === "diffusion") {
    return (
      <Flex direction="column" gap={space.section}>
        <PageHeader title="Diffusion (ALPS)" description="The ALPS index of every subject that has been processed, with the settings behind each value." />
        <DiffusionResultsTable ws={ws} />
      </Flex>
    );
  }
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader
        title="Connectivity"
        description="The correlation matrices of every processed subject: the file index for your analysis tools and a look at each matrix."
      />
      <ConnectivityResultsTable ws={ws} />
      <ConnectivityMatrixView ws={ws} />
    </Flex>
  );
}
