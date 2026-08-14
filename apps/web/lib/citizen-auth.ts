"use client";

import {
  InMemoryWebStorage,
  User,
  UserManager,
  WebStorageStateStore,
} from "oidc-client-ts";

let manager: UserManager | null | undefined;

export function isCitizenOidcConfigured(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_OIDC_ISSUER?.trim() &&
      process.env.NEXT_PUBLIC_OIDC_CLIENT_ID?.trim(),
  );
}

export function getCitizenUserManager(): UserManager | null {
  if (typeof window === "undefined" || !isCitizenOidcConfigured()) return null;
  if (manager !== undefined) return manager;

  manager = new UserManager({
    authority: process.env.NEXT_PUBLIC_OIDC_ISSUER!.trim(),
    client_id: process.env.NEXT_PUBLIC_OIDC_CLIENT_ID!.trim(),
    redirect_uri:
      process.env.NEXT_PUBLIC_OIDC_CITIZEN_REDIRECT_URI?.trim() ||
      `${window.location.origin}/auth/callback`,
    post_logout_redirect_uri:
      process.env.NEXT_PUBLIC_OIDC_CITIZEN_POST_LOGOUT_REDIRECT_URI?.trim() ||
      `${window.location.origin}/`,
    response_type: "code",
    scope: process.env.NEXT_PUBLIC_OIDC_SCOPES?.trim() || "openid profile",
    automaticSilentRenew: false,
    loadUserInfo: false,
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
  return manager;
}

export type CitizenReturnUrl = "/file" | "/track";

export async function beginCitizenSignIn(returnUrl: CitizenReturnUrl = "/file"): Promise<void> {
  const userManager = getCitizenUserManager();
  if (!userManager) throw new Error("Citizen sign-in is not configured");
  await userManager.signinRedirect({ state: { returnUrl } });
}

export async function beginCitizenRegistration(): Promise<void> {
  const userManager = getCitizenUserManager();
  if (!userManager) throw new Error("Citizen sign-in is not configured");
  await userManager.signinRedirect({
    extraQueryParams: { prompt: "create" },
    state: { returnUrl: "/file" },
  });
}

export function getCitizenReturnUrl(user: User): CitizenReturnUrl {
  if (typeof user.state === "object" && user.state !== null && "returnUrl" in user.state) {
    return (user.state as { returnUrl?: unknown }).returnUrl === "/track" ? "/track" : "/file";
  }
  return "/file";
}

export async function completeCitizenSignIn(): Promise<User> {
  const userManager = getCitizenUserManager();
  if (!userManager) throw new Error("Citizen sign-in is not configured");
  return userManager.signinRedirectCallback();
}

export async function getCitizenUser(): Promise<User | null> {
  const userManager = getCitizenUserManager();
  if (!userManager) return null;
  return userManager.getUser();
}

export async function signOutCitizen(): Promise<void> {
  const userManager = getCitizenUserManager();
  if (!userManager) return;
  await userManager.removeUser();
  await userManager.signoutRedirect();
}
