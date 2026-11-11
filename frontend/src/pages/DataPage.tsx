import { PageHeader } from "../components/ui/Layout";
import { SubjectsTab } from "./data/SubjectsTab";

/** Data: the subjects of this workspace and the files each one has. Bringing scans in is the Import page. */
export function DataPage({ ws }: { ws: string }) {
  return (
    <>
      <PageHeader title="Data" description="The subjects of this workspace and the files each one has." />
      <SubjectsTab ws={ws} />
    </>
  );
}
