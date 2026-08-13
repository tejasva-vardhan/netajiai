"use client";

export type PublicTransparency = {
  policy_version: string;
  generated_at: string;
  last_updated_at: string | null;
  total_complaints: number;
  status_counts: Record<string, number>;
  execution_zone_counts: Record<string, number>;
  escalated_count: number;
  mapping_in_progress_count: number;
};

export class PublicApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "PublicApiError";
  }
}

const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001").replace(/\/$/, "");

export async function getPublicTransparency(): Promise<PublicTransparency> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/v1/public/transparency`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    throw new PublicApiError(0, "Public transparency service is unavailable.");
  }
  if (response.status === 404) {
    throw new PublicApiError(404, "Public transparency is not enabled for this deployment.");
  }
  if (!response.ok) {
    throw new PublicApiError(response.status, "Public transparency could not be loaded.");
  }
  return (await response.json()) as PublicTransparency;
}
