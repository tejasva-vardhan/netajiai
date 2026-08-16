import * as AuthSession from "expo-auth-session";
import * as Crypto from "expo-crypto";
import { CONVERSATION_SESSION_KEY, PENDING_FILING_DRAFT_KEY } from "./conversation";
import { deleteStoredValue, getStoredValue, setStoredValue } from "./storage";

const API_BASE_URL = (process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8001").replace(/\/$/, "");
const TOKEN_KEY = "aineta.access_token";
const REFRESH_TOKEN_KEY = "aineta.refresh_token";
const AUTH_SESSION_KEY = "aineta.auth_session_id";
const LAST_RECEIPT_TOKEN_KEY = "aineta.last_receipt_token";
const oidcIssuer = process.env.EXPO_PUBLIC_OIDC_ISSUER?.trim() ?? "";
const oidcClientId = process.env.EXPO_PUBLIC_OIDC_CLIENT_ID?.trim() ?? "";
const oidcScopes = (process.env.EXPO_PUBLIC_OIDC_SCOPES ?? "openid profile")
  .split(/[ ,]+/)
  .map((scope: string) => scope.trim())
  .filter(Boolean);

let activeRefresh: Promise<string | null> | null = null;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type LocationCapture = {
  latitude: number;
  longitude: number;
  accuracy_m: number;
  source: "device_gps";
};

export type PublicComplaint = {
  complaint_id: string;
  status: string;
  version: number;
  issue_type: string | null;
  execution_zone_state: string;
  created_at: string;
  updated_at: string;
};

export type ComplaintTimelineItem = {
  event_type: string;
  from_status: string | null;
  status: string;
  escalation_level: number | null;
  occurred_at: string;
};

export type ComplaintTracking = PublicComplaint & {
  description: string | null;
  jurisdiction_code: string | null;
  disclosure_mode: string;
  last_citizen_resolution_outcome: "fully_solved" | "partially_solved" | "not_solved" | null;
  timeline: ComplaintTimelineItem[];
};

export type EvidenceUpload = {
  evidence_asset_id: string;
  status: string;
  upload_mode: "single" | "multipart";
  upload_url: string | null;
  upload_method: "PUT" | null;
  upload_headers: Record<string, string>;
  multipart_upload_id: string | null;
  part_size: number | null;
  part_count: number | null;
  parts: EvidencePartUploadGrant[];
  completed_parts: number[];
};

export type EvidencePartUploadGrant = {
  part_number: number;
  upload_url: string;
  upload_method: "PUT";
  upload_headers: Record<string, string>;
  upload_expires_at: string;
};

export type EvidenceCompletion = {
  evidence_asset_id: string;
  status: "uploaded" | "review_required" | "verified" | "rejected";
  reason_codes: string[];
};

export type ComplaintReceipt = {
  complaint_id: string;
  status: string;
  version: number;
  execution_zone_state: string;
  created_at: string;
  tracking_token: string;
};

export type ComplaintDraft = {
  issue_type: string | null;
  description: string | null;
  language: string;
  missing_fields: string[];
  confidence: number;
};

export type IdentityVerificationStatus = {
  provider: "digilocker" | "temporary";
  status: "verified" | "pending" | "rejected" | "unavailable";
  verification_id: string | null;
  verified_at: string | null;
  expires_at: string | null;
};

export type ConversationSource = {
  source_id: string;
  title: string;
  url: string;
  verified_at: string | null;
};

export type ConversationDraft = {
  issue_type: string | null;
  description: string | null;
  language: string;
  missing_fields: string[];
  confidence: number;
};

export type ConversationTurn = {
  session_id: string;
  response_id: string;
  intent: string;
  confidence: number;
  response_text: string;
  next_action:
    | "start_filing"
    | "verify_identity"
    | "provide_receipt"
    | "scheme_answer"
    | "scheme_unavailable"
    | "continue_chat"
    | "safety_refusal";
  complaint_draft: ConversationDraft | null;
  scheme_sources: ConversationSource[];
};

export type WorkflowSignalResponse = {
  complaint_id: string;
  signal_id: string;
  accepted: boolean;
  reply_id: string | null;
  reply_classification: "substantive" | "weak" | "duplicate" | "unavailable" | null;
};

export type CitizenResolutionOutcome = "fully_solved" | "partially_solved" | "not_solved";

export type DisclosureConsentResponse = {
  complaint_id: string;
  disclosure_mode: "verified_citizen" | "public_name";
  public_disclosure_eligible: boolean;
  policy_version: string;
  consented_at: string;
};

export type ComplaintCategory = {
  code: string;
  icon: string;
  label_hi: string;
  label_en: string;
  spoken_hi: string;
};

export type ComplaintCategoryCatalog = {
  version: string;
  items: ComplaintCategory[];
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  return requestWithRefresh<T>(path, init, true);
}

async function requestWithRefresh<T>(
  path: string,
  init: RequestInit,
  allowRefresh: boolean,
): Promise<T> {
  const token = await getStoredValue(TOKEN_KEY);
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    if (response.status === 401 && allowRefresh && await refreshAccessToken()) {
      return requestWithRefresh<T>(path, init, false);
    }
    const body = await response.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // Keep non-JSON provider/proxy responses readable below.
    }
    if (response.status === 401) throw new ApiError(401, "Aapka session expire ho gaya. Dobara sign-in karein.");
    if (response.status === 429) {
      const retryAfterHeader = response.headers.get("Retry-After");
      const retryAfterSeconds = retryAfterHeader && /^\d+$/.test(retryAfterHeader)
        ? Number.parseInt(retryAfterHeader, 10)
        : null;
      const waitMessage = retryAfterSeconds && retryAfterSeconds < 3600
        ? ` ${Math.max(Math.ceil(retryAfterSeconds / 60), 1)} minute(s) baad dobara koshish karein.`
        : " Thodi der baad dobara koshish karein.";
      throw new ApiError(429, `Bahut zyada requests.${waitMessage}`, retryAfterSeconds);
    }
    throw new ApiError(response.status, detail || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export async function saveAccessToken(token: string, refreshToken?: string): Promise<void> {
  // These capabilities belong to the previous authenticated account. Do not
  // let a sign-in transition reuse its conversation, draft, or receipt.
  const cleared = await Promise.all([
    clearStoredValue(CONVERSATION_SESSION_KEY),
    clearStoredValue(PENDING_FILING_DRAFT_KEY),
    clearStoredValue(LAST_RECEIPT_TOKEN_KEY),
  ]);
  if (cleared.some((value) => !value)) {
    throw new Error("Secure local session storage is unavailable");
  }

  try {
    await setStoredValue(TOKEN_KEY, token);
    if (refreshToken) {
      await setStoredValue(REFRESH_TOKEN_KEY, refreshToken);
    } else {
      await deleteStoredValue(REFRESH_TOKEN_KEY);
    }
    // This is a local queue binding, not an authentication credential.
    await setStoredValue(AUTH_SESSION_KEY, Crypto.randomUUID());
  } catch (error) {
    // Do not leave a partially activated account behind if one secure-store
    // write fails during the sign-in transition.
    await Promise.all([
      clearStoredValue(TOKEN_KEY),
      clearStoredValue(REFRESH_TOKEN_KEY),
      clearStoredValue(AUTH_SESSION_KEY),
    ]);
    throw error;
  }
}

async function clearStoredValue(key: string): Promise<boolean> {
  try {
    await deleteStoredValue(key);
    return true;
  } catch {
    try {
      // An empty value is intentionally invalid for all capability readers and
      // removes sensitive text even when the platform delete operation fails.
      await setStoredValue(key, "");
      return true;
    } catch {
      return false;
    }
  }
}

async function saveRefreshedAccessToken(token: string, refreshToken?: string): Promise<void> {
  await setStoredValue(TOKEN_KEY, token);
  if (refreshToken) await setStoredValue(REFRESH_TOKEN_KEY, refreshToken);
}

async function refreshAccessToken(): Promise<string | null> {
  if (activeRefresh) return activeRefresh;
  activeRefresh = refreshAccessTokenInternal().finally(() => {
    activeRefresh = null;
  });
  return activeRefresh;
}

async function refreshAccessTokenInternal(): Promise<string | null> {
  const refreshToken = await getStoredValue(REFRESH_TOKEN_KEY);
  if (!refreshToken || !oidcIssuer || !oidcClientId) return null;
  try {
    const discovery = await AuthSession.fetchDiscoveryAsync(oidcIssuer);
    if (!discovery.tokenEndpoint) return null;
    const tokenResponse = await AuthSession.refreshAsync(
      { clientId: oidcClientId, refreshToken, scopes: oidcScopes },
      discovery,
    );
    await saveRefreshedAccessToken(tokenResponse.accessToken, tokenResponse.refreshToken ?? refreshToken);
    return tokenResponse.accessToken;
  } catch {
    return null;
  }
}

export async function getAccessToken(): Promise<string | null> {
  return getStoredValue(TOKEN_KEY);
}

export async function getAuthSessionId(): Promise<string | null> {
  return getStoredValue(AUTH_SESSION_KEY);
}

/** Keep only the latest user-owned receipt capability in platform secure storage. */
export async function saveLastReceiptToken(token: string): Promise<void> {
  const normalized = token.trim();
  if (!normalized) throw new Error("Receipt token is required");
  await setStoredValue(LAST_RECEIPT_TOKEN_KEY, normalized);
}

export async function getLastReceiptToken(): Promise<string | null> {
  return getStoredValue(LAST_RECEIPT_TOKEN_KEY);
}

export async function startIdentityVerification(): Promise<{
  authorization_url: string;
  expires_at: string;
}> {
  return request("/api/v1/identity/digilocker/start", { method: "POST" });
}

export async function getIdentityVerificationStatus(): Promise<IdentityVerificationStatus> {
  return request<IdentityVerificationStatus>("/api/v1/identity/digilocker/status", {
    method: "GET",
  });
}

export async function getComplaintCategories(): Promise<ComplaintCategoryCatalog> {
  return request<ComplaintCategoryCatalog>("/api/v1/complaints/categories", {
    method: "GET",
  });
}

export async function createEvidenceUpload(input: {
  assetType: "photo" | "audio";
  contentType: string;
  byteSize: number;
  sha256: string;
  captureAttestation: string;
  location: LocationCapture;
  idempotencyKey?: string;
}): Promise<EvidenceUpload> {
  return request<EvidenceUpload>("/api/v1/evidence/uploads", {
    method: "POST",
    headers: { "Idempotency-Key": input.idempotencyKey ?? Crypto.randomUUID() },
    body: JSON.stringify({
      asset_type: input.assetType,
      content_type: input.contentType,
      byte_size: input.byteSize,
      client_sha256: input.sha256,
      capture_attestation: input.captureAttestation,
      location: input.location,
    }),
  });
}

export async function uploadFile(
  upload: EvidenceUpload,
  file: Blob,
): Promise<void> {
  if (!upload.upload_url || upload.upload_method !== "PUT") {
    throw new Error("The evidence storage provider did not return a usable upload URL");
  }
  const response = await fetch(upload.upload_url, {
    method: "PUT",
    headers: upload.upload_headers,
    body: file,
  });
  if (!response.ok) throw new Error(`Evidence upload failed (${response.status})`);
}

export async function uploadPart(
  grant: EvidencePartUploadGrant,
  part: Blob,
): Promise<string> {
  const response = await fetch(grant.upload_url, {
    method: "PUT",
    headers: grant.upload_headers,
    body: part,
  });
  if (!response.ok) throw new Error(`Evidence part upload failed (${response.status})`);
  const etag = response.headers.get("etag");
  if (!etag) throw new Error("Evidence storage did not return a part ETag");
  return etag;
}

export async function completeEvidencePart(
  evidenceAssetId: string,
  partNumber: number,
  input: { etag: string; sha256: string; byteSize: number },
): Promise<void> {
  await request(`/api/v1/evidence/${evidenceAssetId}/parts/${partNumber}`, {
    method: "POST",
    body: JSON.stringify({
      etag: input.etag,
      sha256: input.sha256,
      byte_size: input.byteSize,
    }),
  });
}

export async function completeEvidenceUpload(id: string): Promise<EvidenceCompletion> {
  return request<EvidenceCompletion>(`/api/v1/evidence/${id}/complete`, { method: "POST" });
}

export async function createComplaint(input: {
  issueType: string;
  description: string;
  language: string;
  evidenceAssetIds: string[];
  idempotencyKey?: string;
}): Promise<ComplaintReceipt> {
  return request<ComplaintReceipt>("/api/v1/complaints", {
    method: "POST",
    headers: { "Idempotency-Key": input.idempotencyKey ?? Crypto.randomUUID() },
    body: JSON.stringify({
      issue_type: input.issueType,
      description: input.description,
      language: input.language,
      evidence_asset_ids: input.evidenceAssetIds,
      citizen_confirmation: true,
    }),
  });
}

export async function createComplaintDraft(input: {
  text: string;
  language: string;
}): Promise<ComplaintDraft> {
  return request<ComplaintDraft>("/api/v1/complaints/draft", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function createVoiceComplaintDraft(input: {
  audioAssetId: string;
  language: string;
  idempotencyKey?: string;
}): Promise<ComplaintDraft> {
  const response = await request<{
    draft: ComplaintDraft;
    transcription_language: string;
    transcription_confidence: number;
    transcription_provider: string;
    transcription_model: string;
  }>("/api/v1/complaints/voice-draft", {
    method: "POST",
    headers: { "Idempotency-Key": input.idempotencyKey ?? Crypto.randomUUID() },
    body: JSON.stringify({
      audio_asset_id: input.audioAssetId,
      language: input.language,
    }),
  });
  return response.draft;
}

export async function getPublicComplaint(token: string): Promise<PublicComplaint> {
  return request<PublicComplaint>(`/api/v1/public/complaints/${encodeURIComponent(token)}`, {
    method: "GET",
  });
}

export async function getComplaint(complaintId: string): Promise<ComplaintTracking> {
  return request<ComplaintTracking>(`/api/v1/complaints/${encodeURIComponent(complaintId)}`, {
    method: "GET",
  });
}

export async function sendCitizenConfirmation(
  complaintId: string,
  outcome: CitizenResolutionOutcome,
  idempotencyKey?: string,
): Promise<WorkflowSignalResponse> {
  return request<WorkflowSignalResponse>(
    `/api/v1/complaints/${encodeURIComponent(complaintId)}/citizen-confirmation`,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey ?? Crypto.randomUUID() },
      body: JSON.stringify({ outcome }),
    },
  );
}

export async function recordDisclosureConsent(
  complaintId: string,
  mode: "verified_citizen" | "public_name",
  idempotencyKey?: string,
): Promise<DisclosureConsentResponse> {
  return request<DisclosureConsentResponse>(
    `/api/v1/complaints/${encodeURIComponent(complaintId)}/disclosure-consent`,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey ?? Crypto.randomUUID() },
      body: JSON.stringify({ mode, consent: true }),
    },
  );
}

export async function sendConversationTurn(input: {
  text: string;
  language?: string;
  sessionId?: string | null;
  idempotencyKey?: string;
}): Promise<ConversationTurn> {
  return request<ConversationTurn>("/api/v1/conversations/turn", {
    method: "POST",
    headers: { "Idempotency-Key": input.idempotencyKey ?? Crypto.randomUUID() },
    body: JSON.stringify({
      text: input.text,
      language: input.language ?? "hi-IN",
      session_id: input.sessionId ?? null,
    }),
  });
}

export { API_BASE_URL };
