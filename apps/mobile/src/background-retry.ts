import * as BackgroundTask from "expo-background-task";
import * as TaskManager from "expo-task-manager";
import { retryQueuedCaptures } from "./retry";

export const CAPTURE_RETRY_TASK = "aineta-capture-retry-v1";
const MINIMUM_INTERVAL_MINUTES = 15;

/**
 * This definition must stay at module scope. The OS can start the JS bundle
 * without mounting any React view when it runs the task.
 */
TaskManager.defineTask(CAPTURE_RETRY_TASK, async () => {
  try {
    await retryQueuedCaptures();
    return BackgroundTask.BackgroundTaskResult.Success;
  } catch {
    // The queue remains durable; ask the platform to retry the task later.
    return BackgroundTask.BackgroundTaskResult.Failed;
  }
});

export type BackgroundRetryRegistration =
  | "registered"
  | "unavailable"
  | "failed";

/** Register once; the OS owns the actual execution schedule. */
export async function registerCaptureRetryTask(): Promise<BackgroundRetryRegistration> {
  try {
    const status = await BackgroundTask.getStatusAsync();
    if (status !== BackgroundTask.BackgroundTaskStatus.Available) {
      return "unavailable";
    }
    await BackgroundTask.registerTaskAsync(CAPTURE_RETRY_TASK, {
      minimumInterval: MINIMUM_INTERVAL_MINUTES,
    });
    return "registered";
  } catch {
    // Foreground retry remains available if the native scheduler is absent.
    return "failed";
  }
}
