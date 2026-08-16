import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { registerCaptureRetryTask } from "../src/background-retry";
import { retryQueuedCaptures } from "../src/retry";

export default function RootLayout() {
  useEffect(() => {
    void retryQueuedCaptures().catch(() => {
      // A later foreground launch can retry when secure storage/SQLite is available.
    });
    void registerCaptureRetryTask().catch(() => {
      // Background scheduling is best-effort; foreground retry remains available.
    });
  }, []);

  return (
    <>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false }} />
    </>
  );
}
