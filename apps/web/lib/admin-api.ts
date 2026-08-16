"use client";

export type AdminOverview = {
  total_complaints: number;
  status_counts: Record<string, number>;
  execution_zone_counts: Record<string, number>;
  escalated_count: number;
  mapping_in_progress_count: number;
  last_updated_at: string | null;
};

export type AdminComplaint = {
  complaint_id: string;
  status: string;
  version: number;
  issue_type: string | null;
  execution_zone_state: string;
  escalation_level: number;
  public_disclosure_eligible: boolean;
  jurisdiction_code: string | null;
  issue_cluster_id: string | null;
  supporter_count: number | null;
  created_at: string;
  updated_at: string;
};

export type AdminComplaintPage = {
  items: AdminComplaint[];
  next_cursor: string | null;
};

export type EvidenceReviewItem = {
  evidence_asset_id: string;
  asset_type: "photo" | "video" | "audio";
  content_type: string;
  byte_size: number;
  captured_at: string;
  received_at: string;
  reason_codes: string[];
  preview_url: string;
  preview_expires_at: string;
};

export type EvidenceReviewPage = {
  items: EvidenceReviewItem[];
  next_cursor: string | null;
};

export type SchemeReviewSource = {
  source_id: string;
  title: string;
  publisher: string;
  url: string;
  document_hash: string;
  retrieved_at: string;
};

export type SchemeReviewItem = {
  scheme_id: string;
  scheme_key: string;
  language: string;
  jurisdiction_code: string | null;
  title: string;
  answer_text: string;
  eligibility_summary: Record<string, unknown>;
  search_terms: string;
  version: string;
  effective_from: string | null;
  effective_until: string | null;
  review_status: "pending_review";
  created_at: string;
  updated_at: string;
  sources: SchemeReviewSource[];
};

export type SchemeReviewPage = {
  items: SchemeReviewItem[];
  next_cursor: string | null;
};

export type EvidenceReviewDecision = {
  evidence_asset_id: string;
  status: "verified" | "rejected";
  reason_codes: string[];
  reviewed_at: string;
};

export class AdminApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "AdminApiError";
  }
}

const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001").replace(/\/$/, "");

async function requestAdmin<T>(
  path: string,
  accessToken: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new AdminApiError(0, "The operator service is unavailable.");
  }

  if (!response.ok) {
    if (response.status === 401) throw new AdminApiError(401, "Your operator session has expired.");
    if (response.status === 403) throw new AdminApiError(403, "This account does not have operator access.");
    if (response.status === 429) throw new AdminApiError(429, "Too many operator requests. Please wait and try again.");
    if (response.status >= 500) throw new AdminApiError(response.status, "The operator service is temporarily unavailable.");
    throw new AdminApiError(response.status, "The operator request could not be completed.");
  }
  return (await response.json()) as T;
}

export function getAdminOverview(accessToken: string): Promise<AdminOverview> {
  return requestAdmin<AdminOverview>("/api/v1/admin/overview", accessToken);
}

export function listAdminComplaints(
  accessToken: string,
  options: { executionZoneState?: string } = {},
): Promise<AdminComplaintPage> {
  const query = new URLSearchParams({ limit: "25" });
  if (options.executionZoneState) query.set("execution_zone_state", options.executionZoneState);
  return requestAdmin<AdminComplaintPage>(
    `/api/v1/admin/complaints?${query.toString()}`,
    accessToken,
  );
}

export function getEvidenceReviewQueue(accessToken: string): Promise<EvidenceReviewPage> {
  return requestAdmin<EvidenceReviewPage>("/api/v1/admin/evidence/review-queue?limit=25", accessToken);
}

export function getSchemeReviewQueue(accessToken: string): Promise<SchemeReviewPage> {
  return requestAdmin<SchemeReviewPage>("/api/v1/admin/schemes/review-queue?limit=25", accessToken);
}

export function approveScheme(accessToken: string, schemeId: string): Promise<{ scheme_id: string; status: "approved"; reviewed_by: string; reviewed_at: string }> {
  return requestAdmin(`/api/v1/admin/schemes/${encodeURIComponent(schemeId)}/approve`, accessToken, { method: "POST" });
}

export function decideEvidenceReview(
  accessToken: string,
  evidenceAssetId: string,
  decision: "approve" | "reject",
  reasonCode: string,
  idempotencyKey: string,
): Promise<EvidenceReviewDecision> {
  return requestAdmin<EvidenceReviewDecision>(
    `/api/v1/admin/evidence/${encodeURIComponent(evidenceAssetId)}/review`,
    accessToken,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ decision, reason_code: reasonCode }),
    },
  );
}
