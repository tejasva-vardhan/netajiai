export type Capture = {
  id: string;
  photoUri: string;
  audioUri: string;
  latitude: number;
  longitude: number;
  accuracyM: number;
  issueType: string;
  description: string;
  language: string;
};

export type QueuedCapture = Capture & {
  authSessionId: string;
};

const queue: QueuedCapture[] = [];

export async function queueCapture(capture: QueuedCapture): Promise<void> {
  queue.push(capture);
}

export async function listQueuedCaptures(): Promise<QueuedCapture[]> {
  return [...queue];
}

export async function removeQueuedCapture(id: string): Promise<void> {
  const index = queue.findIndex((capture) => capture.id === id);
  if (index >= 0) queue.splice(index, 1);
}
