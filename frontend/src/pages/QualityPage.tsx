import { ComponentReviewPage } from "./ComponentReviewPage";

/** Quality: for now the artifact labelling (the components MELODIC found). The cross-subject
 * check list comes here next. */
export function QualityPage({ ws }: { ws: string }) {
  return <ComponentReviewPage ws={ws} />;
}
