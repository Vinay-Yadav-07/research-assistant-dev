/** Measured imports take 2.5–6 s (D-080); later than this, the user is told it is slow. */
export const SLOW_IMPORT_SECONDS = 10;
/** Past this, the download is near the backend's limits (D-079), so it may stop soon. */
export const VERY_SLOW_IMPORT_SECONDS = 45;

/** A plain note for a slow import, by elapsed seconds; null while it is still normal. */
export function slowImportNote(seconds: number): string | null {
  if (seconds >= VERY_SLOW_IMPORT_SECONDS)
    return "This is taking much longer than usual. Some repositories are very slow; the import stops by itself if the PDF can't be downloaded.";
  if (seconds >= SLOW_IMPORT_SECONDS)
    return "Still importing: the paper's source or PDF host is responding slowly. You can keep using the page.";
  return null;
}
