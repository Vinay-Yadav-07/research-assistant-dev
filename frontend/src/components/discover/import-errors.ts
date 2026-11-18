/** What a failed import means for the user; never shows raw backend messages. */
export type ImportFailure = { message: string; retryable: boolean };

/** The parts of an API error this needs (matches `ApiError`); `status` 0 = no response. */
export type ImportErrorInfo = {
  status: number;
  code?: string;
  details?: Record<string, unknown>;
};

const OPEN_SOURCE = "Open the source to read it.";

/** Why a PDF location failed, from the backend's `details.reason`. */
const PDF_REASONS: Record<string, string> = {
  access_denied: `The publisher blocks automated downloads of this PDF. ${OPEN_SOURCE}`,
  not_pdf: `The open-access link leads to a web page, not a PDF. ${OPEN_SOURCE}`,
  not_found: `The open-access PDF is no longer at its listed location. ${OPEN_SOURCE}`,
  too_large: "The PDF is larger than the 25 MB limit.",
  redirects: `The PDF link redirects too often. ${OPEN_SOURCE}`,
  unsafe: `The PDF link doesn't point to a public website. ${OPEN_SOURCE}`,
  timeout: "The PDF's host didn't respond in time.",
  network: "The PDF's host couldn't be reached.",
  incomplete: "The PDF download was cut off.",
  server_error: "The PDF's host had a temporary problem.",
};

/** Maps an import error to a message and whether "Try again" makes sense. */
export function importFailure(error: ImportErrorInfo): ImportFailure {
  const details = error.details ?? {};
  const reason = typeof details.reason === "string" ? details.reason : "";
  switch (error.code) {
    case "not_open_access":
      return {
        message: `This paper has no open-access PDF. ${OPEN_SOURCE}`,
        retryable: false,
      };
    case "pdf_unavailable":
    case "unsafe_destination": {
      const retryable = details.retryable === true;
      const message =
        PDF_REASONS[reason] ??
        `The PDF couldn't be downloaded. ${retryable ? "" : OPEN_SOURCE}`.trim();
      return { message, retryable };
    }
    case "source_unavailable": {
      const source = details.source === "arxiv" ? "arXiv" : "OpenAlex";
      if (reason === "quota_exhausted")
        return {
          message: `${source}'s daily request limit has been reached. Try again later.`,
          retryable: false,
        };
      return {
        message: `${source} didn't respond while looking up the paper.`,
        retryable: true,
      };
    }
    case "not_found":
      return {
        message: "The paper or the workspace no longer exists.",
        retryable: false,
      };
    case "document_unreadable":
    case "document_scanned":
      return {
        message: "The PDF downloaded but couldn't be read (it may be scanned).",
        retryable: false,
      };
  }
  if (error.status === 0)
    return { message: "Couldn't reach the server.", retryable: true };
  if (error.status === 401)
    return {
      message: "Your session has expired. Sign in again.",
      retryable: false,
    };
  if (error.status >= 500)
    return {
      message: "The import failed because of a server problem.",
      retryable: true,
    };
  return { message: "The import failed.", retryable: false };
}
