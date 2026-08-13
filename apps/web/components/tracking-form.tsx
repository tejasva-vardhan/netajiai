"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  CitizenApiError,
  CitizenResolutionOutcome,
  ComplaintTracking,
  getComplaint,
  sendCitizenConfirmation,
} from "../lib/citizen-api";
import { beginCitizenSignIn, getCitizenUser, isCitizenOidcConfigured as hasCitizenOidc } from "../lib/citizen-auth";

type PublicComplaint = {
  complaint_id: string;
  status: string;
  version: number;
  issue_type: string | null;
  execution_zone_state: string;
  created_at: string;
  updated_at: string;
};

const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001").replace(/\/$/, "");
const TRACK_TOKEN_KEY = "aineta.track.token";

export default function TrackingForm() {
  const [token, setToken] = useState("");
  const [result, setResult] = useState<PublicComplaint | null>(null);
  const [privateResult, setPrivateResult] = useState<ComplaintTracking | null>(null);
  const [citizenAccessToken, setCitizenAccessToken] = useState<string | null>(null);
  const [confirmedOutcome, setConfirmedOutcome] = useState<CitizenResolutionOutcome | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [confirmationBusy, setConfirmationBusy] = useState(false);
  const [confirmationMessage, setConfirmationMessage] = useState("");

  useEffect(() => {
    const savedToken = window.sessionStorage.getItem(TRACK_TOKEN_KEY);
    if (!savedToken) return;
    window.sessionStorage.removeItem(TRACK_TOKEN_KEY);
    setToken(savedToken);
    void lookup(savedToken);
  }, []);

  async function lookup(tokenValue: string, speakResult = false): Promise<void> {
    const trimmedToken = tokenValue.trim();
    if (!trimmedToken) {
      setError("Receipt token likhna zaroori hai.");
      setResult(null);
      setPrivateResult(null);
      return;
    }
    setLoading(true);
    setError("");
    setConfirmationMessage("");
    setConfirmedOutcome(null);
    setResult(null);
    setPrivateResult(null);
    setCitizenAccessToken(null);
    try {
      const publicResult = await getPublicTracking(trimmedToken);
      setResult(publicResult);
      if (speakResult) speakStatus(publicResult.status);

      try {
        const user = await getCitizenUser();
        if (user) {
          const privateTracking = await getComplaint(user.access_token, publicResult.complaint_id);
          setCitizenAccessToken(user.access_token);
          setPrivateResult(privateTracking);
        }
      } catch {
        // A valid receipt may belong to another citizen; keep the redacted view.
      }
    } catch (reason: unknown) {
      setError(reason instanceof CitizenApiError ? reason.message : "Yeh receipt nahi mili. Token dobara jaanch kar try karein.");
    } finally {
      setLoading(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    await lookup(token);
  }

  async function signInForPrivateTracking(): Promise<void> {
    const trimmedToken = token.trim();
    if (!trimmedToken) {
      setError("Pehle receipt token likhein.");
      return;
    }
    setError("");
    window.sessionStorage.setItem(TRACK_TOKEN_KEY, trimmedToken);
    try {
      await beginCitizenSignIn("/track");
    } catch {
      window.sessionStorage.removeItem(TRACK_TOKEN_KEY);
      setError("Citizen sign-in abhi shuru nahi ho saka. Dobara koshish karein.");
    }
  }

  async function confirmResolution(outcome: CitizenResolutionOutcome): Promise<void> {
    if (!privateResult || !citizenAccessToken) return;
    setConfirmationBusy(true);
    setError("");
    setConfirmationMessage("");
    try {
      await sendCitizenConfirmation(
        citizenAccessToken,
        privateResult.complaint_id,
        outcome,
        `web:citizen-confirmation:${privateResult.complaint_id}:${outcome}`,
      );
      setConfirmedOutcome(outcome);
      setConfirmationMessage(resolutionMessage(outcome));
      try {
        setPrivateResult(await getComplaint(citizenAccessToken, privateResult.complaint_id));
      } catch {
        // The accepted signal is durable even if the follow-up read is delayed.
      }
    } catch (reason: unknown) {
      if (reason instanceof CitizenApiError && reason.status === 409) {
        setError("Is complaint par abhi ek aur pushti process mein hai.");
      } else {
        setError("Pushti nahi pahunchi. Network check karke dobara try karein.");
      }
    } finally {
      setConfirmationBusy(false);
    }
  }

  const privateViewAvailable = Boolean(privateResult && citizenAccessToken);
  const signInAvailable = Boolean(result && hasCitizenOidc() && !privateViewAvailable);

  return (
    <section className="tracking-panel" aria-live="polite">
      <form onSubmit={submit}>
        <label htmlFor="receipt-token">Receipt token</label>
        <input
          id="receipt-token"
          name="receipt-token"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          placeholder="Jaise: receipt token"
          aria-describedby="receipt-help"
        />
        <p id="receipt-help" className="field-help">Token app ki receipt screen par milta hai.</p>
        <button className="button button-primary full-width" type="submit" disabled={loading}>
          {loading ? "Status dekha ja raha hai…" : "Status dekhein"}
        </button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <article className="result-card">
          <p className="result-label">Current status</p>
          <div className={`status-presentation status-${statusPresentation(result.status).tone}`} aria-live="polite">
            <span className="status-icon" aria-hidden="true">{statusPresentation(result.status).icon}</span>
            <div className="status-copy">
              <h2>{statusPresentation(result.status).label}</h2>
              <p>{statusPresentation(result.status).spokenLabel}</p>
            </div>
          </div>
          <button
            className="speak-status"
            type="button"
            onClick={() => speakStatus(result.status)}
            aria-label="Status Hindi mein sunayein"
          >
            🔊 Status sunayein
          </button>
          <dl>
            <div><dt>Issue</dt><dd>{result.issue_type ?? "Civic issue"}</dd></div>
            <div><dt>Routing</dt><dd>{humanizeRouting(result.execution_zone_state)}</dd></div>
            <div><dt>Last updated</dt><dd>{formatDate(result.updated_at)}</dd></div>
          </dl>

          {privateViewAvailable && privateResult && (
            <PrivateTrackingPanel
              result={privateResult}
              confirmedOutcome={confirmedOutcome}
              confirmationBusy={confirmationBusy}
              confirmationMessage={confirmationMessage}
              onConfirm={(outcome) => void confirmResolution(outcome)}
            />
          )}
          {signInAvailable && (
            <div className="readback-card" role="group" aria-label="Private tracking sign-in">
              <h2>Apni private tracking dekhein</h2>
              <p>Citizen sign-in ke baad aap timeline dekh sakte hain aur kaam hua ya nahi bata sakte hain.</p>
              <button className="button button-secondary" type="button" onClick={() => void signInForPrivateTracking()}>
                Citizen sign-in
              </button>
            </div>
          )}
          <p className="result-note">
            {privateViewAvailable
              ? "Yeh private citizen view hai. Aapki complaint ki personal details public nahi dikhayi jaati."
              : "Yeh public-safe update hai. Detailed complaint view ke liye apne account/app ka istemal karein."}
          </p>
        </article>
      )}
    </section>
  );
}

function PrivateTrackingPanel({
  result,
  confirmedOutcome,
  confirmationBusy,
  confirmationMessage,
  onConfirm,
}: {
  result: ComplaintTracking;
  confirmedOutcome: CitizenResolutionOutcome | null;
  confirmationBusy: boolean;
  confirmationMessage: string;
  onConfirm: (outcome: CitizenResolutionOutcome) => void;
}) {
  const confirmationDue = result.status === "fix_reported" || result.status === "awaiting_citizen_confirmation";
  return (
    <div className="private-tracking" aria-label="Private complaint details">
      <p className="result-label">Private citizen view</p>
      {confirmationDue && !confirmedOutcome && (
        <div className="readback-card" role="group" aria-label="Complaint resolution choice">
          <h2>Kaam kitna hua?</h2>
          <p>Aapki choice se AI Neta agla follow-up karega.</p>
          <div className="resolution-actions">
            <button className="button button-primary" type="button" disabled={confirmationBusy} onClick={() => onConfirm("fully_solved")}>
              ✅ Haan, kaam ho gaya
            </button>
            <button className="button resolution-partial" type="button" disabled={confirmationBusy} onClick={() => onConfirm("partially_solved")}>
              🟡 Thoda hua, baaki chahiye
            </button>
            <button className="button resolution-unsolved" type="button" disabled={confirmationBusy} onClick={() => onConfirm("not_solved")}>
              ❌ Nahi, kaam nahi hua
            </button>
          </div>
        </div>
      )}
      {confirmationMessage && <p className="success" role="status">{confirmationMessage}</p>}
      {result.timeline.length > 0 && (
        <div className="timeline" aria-label="Complaint timeline">
          <h2>Ab tak kya hua</h2>
          {result.timeline.map((item, index) => (
            <div className="timeline-item" key={`${item.event_type}-${item.occurred_at}-${index}`}>
              <strong>{humanizeStatus(item.status)}</strong>
              <span>{formatDate(item.occurred_at)}</span>
              {item.reason_code && <span>{humanizeStatus(item.reason_code)}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

async function getPublicTracking(token: string): Promise<PublicComplaint> {
  let response: Response;
  try {
    response = await fetch(
      `${apiBaseUrl}/api/v1/public/complaints/${encodeURIComponent(token)}`,
      { headers: { Accept: "application/json" }, cache: "no-store" },
    );
  } catch {
    throw new CitizenApiError(0, "Tracking service is unavailable. Please try again.");
  }
  if (response.status === 404) throw new CitizenApiError(404, "Yeh receipt nahi mili. Token dobara jaanch kar try karein.");
  if (!response.ok) throw new CitizenApiError(response.status, "Tracking service is temporarily unavailable.");
  return (await response.json()) as PublicComplaint;
}

function statusPresentation(status: string): StatusPresentation {
  if (status === "closed") {
    return { label: "Kaam poora bataya gaya", spokenLabel: "Kaam poora bataya gaya hai", icon: "✅", tone: "green" };
  }
  if (status === "escalated" || status === "not_accepted") {
    return { label: "Follow-up zaroori hai", spokenLabel: "Is shikayat par follow-up zaroori hai", icon: "⚠️", tone: "red" };
  }
  if (status === "fix_reported" || status === "awaiting_citizen_confirmation") {
    return { label: "Aapki pushti zaroori hai", spokenLabel: "Aapki pushti zaroori hai", icon: "🙋", tone: "blue" };
  }
  if (status === "sent" || status === "awaiting_response") {
    return { label: "Department ke jawab ka intezar", spokenLabel: "Department ke jawab ka intezar hai", icon: "⏳", tone: "yellow" };
  }
  return { label: "Jaanch aur mapping chal rahi hai", spokenLabel: "Jaanch aur mapping chal rahi hai", icon: "🔎", tone: "neutral" };
}

type StatusPresentation = {
  label: string;
  spokenLabel: string;
  icon: string;
  tone: "green" | "yellow" | "blue" | "red" | "neutral";
};

function resolutionMessage(outcome: CitizenResolutionOutcome): string {
  if (outcome === "fully_solved") return "Aapki pushti mil gayi. Complaint band hone ka update thodi der mein dikhega.";
  if (outcome === "partially_solved") return "Aapne bataya ki kaam kuchh hua hai. Baaki kaam ke liye follow-up jaari rahega.";
  return "Aapki baat mil gayi. Complaint dobara follow-up mein ja rahi hai.";
}

function speakStatus(status: string): void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
  const presentation = statusPresentation(status);
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(`Aapki shikayat ka status: ${presentation.spokenLabel}`);
  utterance.lang = "hi-IN";
  utterance.rate = 0.88;
  window.speechSynthesis.speak(utterance);
}

function humanizeStatus(status: string): string {
  return status.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function humanizeRouting(state: string): string {
  return state === "mapping_in_progress" ? "Department mapping chal rahi hai" : humanizeStatus(state);
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Update available" : new Intl.DateTimeFormat("hi-IN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
