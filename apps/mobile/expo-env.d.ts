/// <reference types="expo/types" />

declare namespace NodeJS {
  interface ProcessEnv {
    EXPO_PUBLIC_API_BASE_URL?: string;
    EXPO_PUBLIC_CAPTURE_ATTESTATION_MODE?: "development" | "production";
    EXPO_PUBLIC_OIDC_ISSUER?: string;
    EXPO_PUBLIC_OIDC_CLIENT_ID?: string;
    EXPO_PUBLIC_OIDC_SCOPES?: string;
  }
}
