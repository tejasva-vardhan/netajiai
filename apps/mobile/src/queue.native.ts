import * as SQLite from "expo-sqlite";
import * as Crypto from "expo-crypto";
import { getStoredValue, setStoredValue } from "./storage";

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
  /** Local binding that prevents another signed-in account from retrying it. */
  authSessionId: string;
};

let databasePromise: Promise<SQLite.SQLiteDatabase> | null = null;
const DATABASE_NAME = "aineta-capture-queue-v2.db";
const DATABASE_KEY_NAME = "aineta.capture_queue_database_key";

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function getDatabaseKey(): Promise<string> {
  const existing = await getStoredValue(DATABASE_KEY_NAME);
  if (existing) return existing;
  const generated = bytesToHex(await Crypto.getRandomBytesAsync(32));
  await setStoredValue(DATABASE_KEY_NAME, generated);
  return generated;
}

async function getDatabase(): Promise<SQLite.SQLiteDatabase> {
  databasePromise ??= initializeDatabase().catch((error: unknown) => {
    databasePromise = null;
    throw error;
  });
  return databasePromise;
}

async function initializeDatabase(): Promise<SQLite.SQLiteDatabase> {
  const database = await SQLite.openDatabaseAsync(DATABASE_NAME);
  const key = await getDatabaseKey();
  // The key is generated once and held in platform secure storage. It is
  // hex-only, so interpolation cannot introduce SQL syntax.
  await database.execAsync(`PRAGMA key = '${key}'`);
  await database.execAsync(
    "CREATE TABLE IF NOT EXISTS capture_queue (id TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);",
  );
  return database;
}

export async function queueCapture(capture: QueuedCapture): Promise<void> {
  const db = await getDatabase();
  await db.runAsync(
    "INSERT OR REPLACE INTO capture_queue (id, payload, created_at) VALUES (?, ?, ?)",
    capture.id,
    JSON.stringify(capture),
    new Date().toISOString(),
  );
}

export async function listQueuedCaptures(): Promise<QueuedCapture[]> {
  const db = await getDatabase();
  const rows = await db.getAllAsync<{ id: string; payload: string }>(
    "SELECT id, payload FROM capture_queue ORDER BY created_at ASC",
  );
  const captures: QueuedCapture[] = [];
  for (const row of rows) {
    try {
      const parsed = JSON.parse(row.payload) as Partial<QueuedCapture>;
      if (
        typeof parsed.id !== "string"
        || parsed.id !== row.id
        || typeof parsed.photoUri !== "string"
        || typeof parsed.audioUri !== "string"
        || typeof parsed.latitude !== "number"
        || !Number.isFinite(parsed.latitude)
        || typeof parsed.longitude !== "number"
        || !Number.isFinite(parsed.longitude)
        || typeof parsed.accuracyM !== "number"
        || !Number.isFinite(parsed.accuracyM)
        || typeof parsed.issueType !== "string"
        || typeof parsed.description !== "string"
        || typeof parsed.language !== "string"
        || typeof parsed.authSessionId !== "string"
      ) {
        throw new Error("invalid queued capture");
      }
      captures.push(parsed as QueuedCapture);
    } catch {
      // A corrupt local row must not poison every later retry attempt.
      await db.runAsync("DELETE FROM capture_queue WHERE id = ?", row.id);
    }
  }
  return captures;
}

export async function removeQueuedCapture(id: string): Promise<void> {
  const db = await getDatabase();
  await db.runAsync("DELETE FROM capture_queue WHERE id = ?", id);
}
