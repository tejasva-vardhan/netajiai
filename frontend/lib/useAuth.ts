"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { clearAuthToken, getAuthToken, withAuthHeaders } from "@/lib/api";

type UseAuthOptions = {
  redirectOnUnauthorizedTo?: string;
};

export function useAuth(options?: UseAuthOptions) {
  const router = useRouter();
  const redirectPath = options?.redirectOnUnauthorizedTo ?? "/login";
  const [token, setToken] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    setToken(getAuthToken());
    setIsReady(true);
  }, []);

  const logout = useCallback(
    (redirectTo: string = "/") => {
      clearAuthToken();
      setToken(null);
      router.replace(redirectTo);
    },
    [router]
  );

  const handleUnauthorized = useCallback(() => {
    clearAuthToken();
    setToken(null);
    router.replace(redirectPath);
  }, [redirectPath, router]);

  const authFetch = useCallback(
    async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const mergedHeaders = withAuthHeaders((init?.headers as HeadersInit) ?? undefined);
      const res = await fetch(input, { ...init, headers: mergedHeaders });
      if (res.status === 401) {
        handleUnauthorized();
      }
      return res;
    },
    [handleUnauthorized]
  );

  return useMemo(
    () => ({
      token,
      isReady,
      isLoggedIn: !!token,
      logout,
      handleUnauthorized,
      authFetch,
    }),
    [authFetch, handleUnauthorized, isReady, logout, token]
  );
}

