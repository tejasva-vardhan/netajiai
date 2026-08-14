"use client";

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

export type VerificationStatus = {
  provider: "digilocker" | "temporary";
  status: "verified" | "pending" | "rejected" | "unavailable";
  verification_id: string | null;
  verified_at: string | null;
  expires_at: string | null;
};

export type CaptureSession = {
  capture_token: string;
  expires_at: string;
};

export type EvidenceUpload = {
  evidence_asset_id: string;
  status: "upload_pending" | "uploaded" | "review_required" | "verified" | "rejected";
  upload_mode: "single" | "multipart";
  upload_url: string | null;
  upload_method: "PUT" | null;
  upload_headers: Record<string, string>;
  multipart_upload_id: string | null;
  part_size: number | null;
  part_count: number | null;
  parts: Array<{
    part_number: number;
    upload_url: string;
    upload_method: "PUT";
    upload_headers: Record<string, string>;
    upload_expires_at: string;
  }>;
  completed_parts: number[];
};

export type EvidenceCompletion = {
  evidence_asset_id: string;
  status: "uploaded" | "review_required" | "verified" | "rejected";
  reason_codes: string[];
};

export type ComplaintReceipt = {
  complaint_id: string;
  status: string;
  tracking_token: string;
};

export type ComplaintTimelineItem = {
  event_type: string;
  reason_code: string | null;
  from_status: string | null;
  status: string;
  escalation_level: number | null;
  occurred_at: string;
};

export type CitizenResolutionOutcome = "fully_solved" | "partially_solved" | "not_solved";

export type ComplaintTracking = {
  complaint_id: string;
  status: string;
  issue_type: string | null;
  version: number;
  description: string | null;
  jurisdiction_code: string | null;
  execution_zone_state: string;
  escalation_level: number;
  disclosure_mode: string;
  last_citizen_resolution_outcome: CitizenResolutionOutcome | null;
  issue_cluster_id: string | null;
  supporter_count: number | null;
  created_at: string;
  updated_at: string;
  timeline: ComplaintTimelineItem[];
};

export type WorkflowSignalResponse = {
  complaint_id: string;
  signal_id: string;
  accepted: boolean;
  reply_id: string | null;
  reply_classification: "substantive" | "weak" | "duplicate" | "unavailable" | null;
};

export type DisclosureConsentResponse = {
  complaint_id: string;
  disclosure_mode: "verified_citizen" | "public_name";
  public_disclosure_eligible: boolean;
  policy_version: string;
  consented_at: string;
};

export type VoiceDraft = {
  draft: {
    issue_type: string | null;
    description: string | null;
    language: string;
    missing_fields: string[];
    confidence: number;
  };
  transcription_language: string;
  transcription_confidence: number;
  transcription_provider: string;
  transcription_model: string;
};

export type ConversationNextAction =
  | "start_filing"
  | "verify_identity"
  | "provide_receipt"
  | "scheme_answer"
  | "scheme_unavailable"
  | "continue_chat"
  | "safety_refusal";

export type ConversationTurnResponse = {
  session_id: string;
  response_id: string;
  intent: "casual" | "scheme" | "filing" | "status" | "continuation";
  confidence: number;
  response_text: string;
  next_action: ConversationNextAction;
  complaint_draft: {
    issue_type: string | null;
    description: string | null;
    language: string;
    missing_fields: string[];
    confidence: number;
  } | null;
  scheme_sources: Array<{ source_id: string; title: string; url: string }>;
};

export class CitizenApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "CitizenApiError";
  }
}

const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001").replace(/\/$/, "");

async function request<T>(path: string, accessToken: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new CitizenApiError(0, "Citizen service is unavailable.");
  }
  if (!response.ok) {
    if (response.status === 401) throw new CitizenApiError(401, "Your citizen session has expired.");
    if (response.status === 403) throw new CitizenApiError(403, "Identity verification is required.");
    if (response.status === 404) throw new CitizenApiError(404, "This citizen service is not enabled.");
    if (response.status === 429) throw new CitizenApiError(429, "Too many requests. Please wait and try again.");
    if (response.status >= 500) throw new CitizenApiError(response.status, "The citizen service is temporarily unavailable.");
    throw new CitizenApiError(response.status, "The request could not be completed.");
  }
  return (await response.json()) as T;
}

export function getVerificationStatus(accessToken: string): Promise<VerificationStatus> {
  return request<VerificationStatus>("/api/v1/identity/digilocker/status", accessToken);
}

export function startIdentityVerification(accessToken: string): Promise<{ authorization_url: string; expires_at: string }> {
  return request("/api/v1/identity/digilocker/start", accessToken, { method: "POST" });
}

export function getComplaintCategories(accessToken: string): Promise<ComplaintCategoryCatalog> {
  return request("/api/v1/complaints/categories", accessToken);
}

export function sendConversationTurn(
  accessToken: string,
  input: {
    text: string;
    language: string;
    sessionId: string | null;
    idempotencyKey: string;
  },
): Promise<ConversationTurnResponse> {
  return request<ConversationTurnResponse>("/api/v1/conversations/turn", accessToken, {
    method: "POST",
    headers: { "Idempotency-Key": input.idempotencyKey },
    body: JSON.stringify({
      text: input.text,
      language: input.language,
      session_id: input.sessionId,
    }),
  });
}

export function createCaptureSession(
  accessToken: string,
  assetType: "photo" | "audio",
  idempotencyKey: string,
): Promise<CaptureSession> {
  return request<CaptureSession>("/api/v1/evidence/capture-sessions", accessToken, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ asset_type: assetType }),
  });
}

export function createEvidenceUpload(
  accessToken: string,
  input: {
    assetType: "photo" | "audio";
    contentType: string;
    byteSize: number;
    sha256: string;
    captureToken: string;
    latitude: number;
    longitude: number;
    accuracyM: number;
    idempotencyKey: string;
  },
): Promise<EvidenceUpload> {
  return request<EvidenceUpload>("/api/v1/evidence/uploads", accessToken, {
    method: "POST",
    headers: { "Idempotency-Key": input.idempotencyKey },
    body: JSON.stringify({
      asset_type: input.assetType,
      content_type: input.contentType,
      byte_size: input.byteSize,
      client_sha256: input.sha256,
      capture_attestation: input.captureToken,
      location: {
        latitude: input.latitude,
        longitude: input.longitude,
        accuracy_m: input.accuracyM,
        source: "browser_gps",
      },
    }),
  });
}

export async function uploadEvidence(upload: EvidenceUpload, blob: Blob): Promise<void> {
  if (!upload.upload_url || upload.upload_method !== "PUT" || upload.upload_mode !== "single") {
    throw new Error("The browser filing path requires a single upload grant.");
  }
  const response = await fetch(upload.upload_url, {
    method: "PUT",
    headers: upload.upload_headers,
    body: blob,
  });
  if (!response.ok) throw new Error("Evidence upload failed.");
}

export function completeEvidenceUpload(accessToken: string, evidenceAssetId: string): Promise<EvidenceCompletion> {
  return request<EvidenceCompletion>(`/api/v1/evidence/${encodeURIComponent(evidenceAssetId)}/complete`, accessToken, { method: "POST" });
}

export function createComplaint(
  accessToken: string,
  input: {
    issueType: string;
    description: string;
    language: string;
    evidenceAssetIds: string[];
    idempotencyKey: string;
  },
): Promise<ComplaintReceipt> {
  return request<ComplaintReceipt>("/api/v1/complaints", accessToken, {
    method: "POST",
    headers: { "Idempotency-Key": input.idempotencyKey },
    body: JSON.stringify({
      issue_type: input.issueType,
      description: input.description,
      language: input.language,
      evidence_asset_ids: input.evidenceAssetIds,
      citizen_confirmation: true,
    }),
  });
}

export function getComplaint(accessToken: string, complaintId: string): Promise<ComplaintTracking> {
  return request<ComplaintTracking>(`/api/v1/complaints/${encodeURIComponent(complaintId)}`, accessToken);
}

export function sendCitizenConfirmation(
  accessToken: string,
  complaintId: string,
  outcome: CitizenResolutionOutcome,
  idempotencyKey: string,
): Promise<WorkflowSignalResponse> {
  return request<WorkflowSignalResponse>(
    `/api/v1/complaints/${encodeURIComponent(complaintId)}/citizen-confirmation`,
    accessToken,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ outcome }),
    },
  );
}

export function recordDisclosureConsent(
  accessToken: string,
  complaintId: string,
  mode: "verified_citizen" | "public_name",
  idempotencyKey: string,
): Promise<DisclosureConsentResponse> {
  return request<DisclosureConsentResponse>(
    `/api/v1/complaints/${encodeURIComponent(complaintId)}/disclosure-consent`,
    accessToken,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ mode, consent: true }),
    },
  );
}

export function createVoiceDraft(
  accessToken: string,
  input: { audioAssetId: string; language: string; idempotencyKey: string },
): Promise<VoiceDraft> {
  return request<VoiceDraft>("/api/v1/complaints/voice-draft", accessToken, {
    method: "POST",
    headers: { "Idempotency-Key": input.idempotencyKey },
    body: JSON.stringify({ audio_asset_id: input.audioAssetId, language: input.language }),
  });
}

export async function sha256Blob(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}
