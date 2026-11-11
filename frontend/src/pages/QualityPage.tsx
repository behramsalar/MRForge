import { Flex } from "@radix-ui/themes";
import { useOverview } from "../api/hooks";
import { SubjectsTable } from "../components/SubjectsTable";
import { QualityReview } from "../components/QualityReview";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { href } from "../lib/router";
import { space } from "../theme/tokens";
import { ComponentReviewPage } from "./ComponentReviewPage";

/** Quality: which subjects need a look, every subject's report, and the artifact labelling. The
 * sidebar lists the three; the address extra says which one is open. */
export function QualityPage({ ws, tab }: { ws: string; tab?: string }) {
  const overview = useOverview(ws);
  const current = tab === "artifacts" || tab === "reports" ? tab : "subjects";
  const rows = (overview.data?.subjects ?? []).filter((s) => s.n_files > 0);
  const empty = overview.data && rows.length === 0;
  const descriptions = {
    subjects: "Check each subject's results and record a decision. MRForge flags problems; it never excludes anyone by itself.",
    reports: "The full report of a subject: quality checks first, then what was done. Choose a subject to open it.",
    artifacts: "Look at each component MELODIC found and decide whether it is brain activity or noise.",
  };
  const titles = { subjects: "Subject review", reports: "Reports", artifacts: "Artifact rejection" };
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader title={titles[current]} description={descriptions[current]} />
      {current === "artifacts" ? (
        <ComponentReviewPage ws={ws} embedded />
      ) : empty ? (
        <EmptyState title="Nothing to check yet" text="Quality checks appear here once subjects have been processed." action="Process data" href={href(ws, "process")} />
      ) : current === "reports" ? (
        <SubjectsTable subjects={rows} onOpen={(l) => (location.hash = href(ws, "subject", l, "results"))} />
      ) : (
        <QualityReview ws={ws} subjects={rows} />
      )}
    </Flex>
  );
}
