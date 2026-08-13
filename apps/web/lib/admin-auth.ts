"use client";

import {
  InMemoryWebStorage,
  User,
  UserManager,
  WebStorageStateStore,
} from "oidc-client-ts";

let manager: UserManager | null | undefined;

export function isAdminOidcConfigured(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_OIDC_ISSUER?.trim() &&
      process.env.NEXT_PUBLIC_OIDC_CLIENT_ID?.trim(),
  );
}

export function getAdminUserManager(): UserManager | null {
  if (typeof window === "undefined" || !isAdminOidcConfigured()) return null;
  if (manager !== undefined) return manager;

  manager = new UserManager({
    authority: process.env.NEXT_PUBLIC_OIDC_ISSUER!.trim(),
    client_id: process.env.NEXT_PUBLIC_OIDC_CLIENT_ID!.trim(),
    redirect_uri:
      process.env.NEXT_PUBLIC_OIDC_ADMIN_REDIRECT_URI?.trim() ||
      `${window.location.origin}/admin/auth/callback`,
    post_logout_redirect_uri:
      process.env.NEXT_PUBLIC_OIDC_ADMIN_POST_LOGOUT_REDIRECT_URI?.trim() ||
      `${window.location.origin}/`,
    response_type: "code",
    scope: process.env.NEXT_PUBLIC_OIDC_SCOPES?.trim() || "openid profile",
    automaticSilentRenew: false,
    loadUserInfo: false,
    // Keep the bearer token in this page runtime only. Redirect state is
    // transient and belongs in sessionStorage for the PKCE callback.
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
  return manager;
}

export async function beginAdminSignIn(): Promise<void> {
  const userManager = getAdminUserManager();
  if (!userManager) throw new Error("Admin sign-in is not configured");
  await userManager.signinRedirect({ state: { returnUrl: "/admin" } });
}

export async function completeAdminSignIn(): Promise<User> {
  const userManager = getAdminUserManager();
  if (!userManager) throw new Error("Admin sign-in is not configured");
  return userManager.signinRedirectCallback();
}

export async function getAdminUser(): Promise<User | null> {
  const userManager = getAdminUserManager();
  if (!userManager) return null;
  return userManager.getUser();
}

export async function signOutAdmin(): Promise<void> {
  const userManager = getAdminUserManager();
  if (!userManager) return;
  await userManager.removeUser();
  await userManager.signoutRedirect();
}
