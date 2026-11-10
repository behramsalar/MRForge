import { Flex, Tabs } from "@radix-ui/themes";
import { useOverview } from "../api/hooks";
import { QualityReview } from "../components/QualityReview";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { href } from "../lib/router";
import { space } from "../theme/tokens";
import { ComponentReviewPage } from "./ComponentReviewPage";

/** Quality: which subjects need a look and each subject's report, and the artifact labelling.
 * Two tabs for now; where the labelling belongs long term is still open. */
export function QualityPage({ ws, tab }: { ws: string; tab?: string }) {
  const overview = useOverview(ws);
  const current = tab === "artifacts" ? "artifacts" : "subjects";
  const rows = (overview.data?.subjects ?? []).filter((s) => s.n_files > 0);
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader
        title="Quality"
        description="Check each subject's results and record a decision. MRForge flags problems; it never excludes anyone by itself."
      />
      <Tabs.Root value={current} onValueChange={(v) => (location.hash = href(ws, "quality", v === "artifacts" ? "artifacts" : undefined))}>
        <Tabs.List>
          <Tabs.Trigger value="subjects">Subjects and reports</Tabs.Trigger>
          <Tabs.Trigger value="artifacts">Artifact rejection</Tabs.Trigger>
        </Tabs.List>
        <div style={{ paddingTop: `var(--space-${space.section})` }}>
          {current === "artifacts" ? (
            <ComponentReviewPage ws={ws} embedded />
          ) : overview.data && rows.length === 0 ? (
            <EmptyState title="Nothing to check yet" text="Quality checks appear here once subjects have been processed." action="Process data" href={href(ws, "process")} />
          ) : (
            <QualityReview ws={ws} subjects={rows} />
          )}
        </div>
      </Tabs.Root>
    </Flex>
  );
}
