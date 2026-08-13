import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { registerCaptureRetryTask } from "../src/background-retry";
import { retryQueuedCaptures } from "../src/retry";

export default function RootLayout() {
  useEffect(() => {
    void retryQueuedCaptures();
    void registerCaptureRetryTask();
  }, []);

  return (
    <>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false }} />
    </>
  );
}
