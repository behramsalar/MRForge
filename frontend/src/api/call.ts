import type { ErrorBody } from "./types";

/** An error from the API in plain language (what happened, why, what to do). */
export class ApiError extends Error {
  body: ErrorBody;
  constructor(body: ErrorBody) {
    super(body.message);
    this.body = body;
  }
}

const UNREACHABLE: ErrorBody = {
  code: "UNREACHABLE",
  message: "The page could not reach MRForge.",
  probable_cause: "The MRForge server may have stopped.",
  suggested_action: "Check that 'mrforge serve' is still running, then reload the page.",
};

/** The server answered but not in our error format (a crash, a proxy page, an old server). */
function fromStatus(status: number): ErrorBody {
  return {
    code: "UNEXPECTED_REPLY",
    message: "MRForge answered, but could not do what was asked.",
    probable_cause: `The server replied with an error (code ${status}).`,
    suggested_action:
      "Try again. If it keeps happening, open the terminal running 'mrforge serve' and look at the last lines.",
  };
}

function toBody(error: unknown, status: number): ErrorBody {
  const e = error as Partial<ErrorBody> | undefined;
  if (e && typeof e.message === "string") return e as ErrorBody;
  return fromStatus(status);
}

/** Unwrap an openapi-fetch result: return the data, or throw an ApiError. */
export async function call<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result;
  try {
    result = await request;
  } catch {
    throw new ApiError(UNREACHABLE);
  }
  if (result.error !== undefined || !result.response.ok) throw new ApiError(toBody(result.error, result.response.status));
  return result.data as T;
}
