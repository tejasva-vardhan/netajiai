import { listQueuedCaptures, removeQueuedCapture } from "./queue";
import { EvidenceRejectedError, submitCapturedComplaint } from "./submission";
import { getAuthSessionId, saveLastReceiptToken } from "./api";

export type RetrySummary = {
  attempted: number;
  completed: number;
  remaining: number;
};

let activeRetry: Promise<RetrySummary> | null = null;

/** Retry durable captures when the citizen reopens the app. */
export function retryQueuedCaptures(): Promise<RetrySummary> {
  if (activeRetry) return activeRetry;
  activeRetry = retryQueuedCapturesInternal().finally(() => {
    activeRetry = null;
  });
  return activeRetry;
}

async function retryQueuedCapturesInternal(): Promise<RetrySummary> {
  const [captures, authSessionId] = await Promise.all([
    listQueuedCaptures(),
    getAuthSessionId(),
  ]);
  const eligibleCaptures = authSessionId
    ? captures.filter((capture) => capture.authSessionId === authSessionId)
    : [];
  let completed = 0;
  for (const capture of eligibleCaptures) {
    try {
      const receipt = await submitCapturedComplaint(capture);
      await removeQueuedCapture(capture.id);
      try {
        await saveLastReceiptToken(receipt.tracking_token);
      } catch {
        // The server receipt is authoritative; secure storage improves the
        // next visit but must not make a completed retry appear failed.
      }
      completed += 1;
    } catch (error) {
      if (error instanceof EvidenceRejectedError) {
        await removeQueuedCapture(capture.id);
        continue;
      }
      // Keep retryable records for the next foreground attempt. Do not log
      // their content.
    }
  }
  const remaining = (await listQueuedCaptures()).length;
  return {
    attempted: eligibleCaptures.length,
    completed,
    remaining,
  };
}
