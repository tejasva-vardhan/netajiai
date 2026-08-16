import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

function webStorage(): Storage | null {
  if (Platform.OS !== "web" || typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** Native values stay in SecureStore; Expo web is only a tab-scoped preview. */
export async function getStoredValue(key: string): Promise<string | null> {
  if (Platform.OS === "web") return webStorage()?.getItem(key) ?? null;
  return SecureStore.getItemAsync(key);
}

export async function setStoredValue(key: string, value: string): Promise<void> {
  if (Platform.OS === "web") {
    const storage = webStorage();
    if (!storage) throw new Error("Web session storage is unavailable");
    storage.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

export async function deleteStoredValue(key: string): Promise<void> {
  if (Platform.OS === "web") {
    const storage = webStorage();
    if (!storage) throw new Error("Web session storage is unavailable");
    storage.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}
