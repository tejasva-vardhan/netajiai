export const CONVERSATION_SESSION_KEY = "aineta.conversation_session_id";
export const PENDING_FILING_DRAFT_KEY = "aineta.pending_filing_draft";

export type PendingFilingDraft = {
  description: string;
  issueType: string | null;
  language: string;
  expiresAt: number;
};

export function isPendingFilingDraftActive(
  value: PendingFilingDraft | null,
): value is PendingFilingDraft {
  return value !== null && value.expiresAt > Date.now();
}

export function parsePendingFilingDraft(raw: string | null): PendingFilingDraft | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<PendingFilingDraft>;
    if (typeof value.description !== "string" || !value.description.trim()) return null;
    if (value.issueType !== null && typeof value.issueType !== "string") return null;
    if (typeof value.expiresAt !== "number" || value.expiresAt <= Date.now()) return null;
    return {
      description: value.description,
      issueType: value.issueType ?? null,
      language: typeof value.language === "string" && value.language ? value.language : "hi-IN",
      expiresAt: value.expiresAt,
    };
  } catch {
    return null;
  }
}
