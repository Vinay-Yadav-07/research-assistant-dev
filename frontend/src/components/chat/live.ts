/**
 * True once the answer a live run ended with is in the loaded history, so the live block can go.
 * The id belongs to the run: a new question starts without one and stays visible (an id kept
 * from the previous answer hid every later question until its answer arrived).
 */
export function answerLoaded(
  answerId: string | undefined,
  history: readonly { id: string }[],
): boolean {
  return answerId !== undefined && history.some((m) => m.id === answerId);
}
