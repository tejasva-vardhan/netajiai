/**
 * FastAPI base URL for browser `fetch` calls.
 *
 * - **Production:** set `NEXT_PUBLIC_API_URL` to your public API (e.g. Render), no trailing slash.
 * - **Local dev:** if unset, defaults to `http://localhost:8000` (ensure CORS allows your Next origin).
 */
const DEFAULT_LOCAL_API = "http://localhost:8000";

export function getApiBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (raw) return raw.replace(/\/$/, "");
  return DEFAULT_LOCAL_API;
}

export const API_BASE = getApiBase();

export const AUTH_TOKEN_STORAGE_KEY = "aineta_token";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  const t = window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
  return t && t.trim().length > 0 ? t.trim() : null;
}

export function setAuthToken(token: string): void {
  if (typeof window === "undefined") return;
  const clean = token.trim();
  if (!clean) return;
  window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, clean);
}

export function clearAuthToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
}

export function withAuthHeaders(init?: HeadersInit): HeadersInit {
  const token = getAuthToken();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  return init ? { ...headers, ...(init as Record<string, string>) } : headers;
}
