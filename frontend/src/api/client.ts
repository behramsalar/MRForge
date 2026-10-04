import createClient from "openapi-fetch";
import type { paths } from "./schema";

/** Where the page remembers which researcher profile is working (see shell/ResearcherProvider). */
export const RESEARCHER_KEY = "mrforge-researcher";

export const api = createClient<paths>({ baseUrl: "" });

// Every request says which profile is working, so the server can tag what that person starts.
// This is a name, not a login: see docs/DECISIONS.md.
api.use({
  onRequest({ request }) {
    try {
      const id = localStorage.getItem(RESEARCHER_KEY);
      if (id) request.headers.set("X-MRForge-User", id);
    } catch {
      /* storage blocked: the request is simply not attributed */
    }
    return request;
  },
});
