"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { User } from "oidc-client-ts";
import {
  CitizenApiError,
  ComplaintCategoryCatalog,
  ComplaintReceipt,
  completeEvidenceUpload,
  createCaptureSession,
  createComplaint,
  createEvidenceUpload,
  createVoiceDraft,
  getComplaintCategories,
  getVerificationStatus,
  recordDisclosureConsent,
  sha256Blob,
  startIdentityVerification,
  uploadEvidence,
} from "../../lib/citizen-api";
import { beginCitizenSignIn, getCitizenUser, isCitizenOidcConfigured, signOutCitizen } from "../../lib/citizen-auth";

type CapturedMedia = { blob: Blob; contentType: string };
type Coordinates = { latitude: number; longitude: number; accuracyM: number };
type VoiceDraftState = { description: string };
type ComplaintLanguage = "hi-IN" | "en-IN" | "hinglish";

function errorMessage(error: unknown): string {
  if (error instanceof CitizenApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Kuchh galat hua. Dobara koshish karein.";
}

export default function FileComplaintPage() {
  const [user, setUser] = useState<User | null>(null);
  const [catalog, setCatalog] = useState<ComplaintCategoryCatalog | null>(null);
  const [verification, setVerification] = useState("loading");
  const [language, setLanguage] = useState<ComplaintLanguage>("hi-IN");
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");
  const [photo, setPhoto] = useState<CapturedMedia | null>(null);
  const [audio, setAudio] = useState<CapturedMedia | null>(null);
  const [location, setLocation] = useState<Coordinates | null>(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [voiceDraft, setVoiceDraft] = useState<VoiceDraftState | null>(null);
  const [pendingEvidenceIds, setPendingEvidenceIds] = useState<string[]>([]);
  const [confirmationRequired, setConfirmationRequired] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<ComplaintReceipt | null>(null);
  const [disclosureSaved, setDisclosureSaved] = useState(false);
  const [disclosureBusy, setDisclosureBusy] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const photoEvidenceKeyRef = useRef<string | null>(null);
  const audioEvidenceKeyRef = useRef<string | null>(null);
  const voiceDraftKeyRef = useRef<string | null>(null);
  const complaintKeyRef = useRef<string | null>(null);

  function resetSubmissionKeys(): void {
    photoEvidenceKeyRef.current = null;
    audioEvidenceKeyRef.current = null;
    voiceDraftKeyRef.current = null;
    complaintKeyRef.current = null;
  }

  function evidenceIdempotencyKey(assetType: "photo" | "audio"): string {
    const keyRef = assetType === "photo" ? photoEvidenceKeyRef : audioEvidenceKeyRef;
    return (keyRef.current ??= crypto.randomUUID());
  }

  useEffect(() => {
    let active = true;
    void getCitizenUser().then((currentUser) => {
      if (!active) return;
      setUser(currentUser);
      if (!currentUser) return;
      void Promise.all([
        getVerificationStatus(currentUser.access_token),
        getComplaintCategories(currentUser.access_token),
      ]).then(([status, categories]) => {
        if (!active) return;
        setVerification(status.status);
        setCatalog(categories);
        setCategory((current) => current || categories.items[0]?.code || "");
      }).catch((reason: unknown) => { if (active) setError(errorMessage(reason)); });
    }).catch((reason: unknown) => { if (active) setError(errorMessage(reason)); });
    return () => {
      active = false;
      cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
      recorderRef.current?.stop();
    };
  }, []);

  function stopCamera() {
    cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
    cameraStreamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraOpen(false);
  }

  async function openCamera() {
    setError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Is browser mein camera available nahi hai.");
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      cameraStreamRef.current = stream;
      setCameraOpen(true);
      if (videoRef.current) { videoRef.current.srcObject = stream; await videoRef.current.play(); }
    } catch (reason: unknown) { setError(errorMessage(reason)); }
  }

  function capturePhoto() {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0 || video.videoHeight === 0) {
      setError("Camera taiyaar nahi hai. Ek pal ruk kar phir koshish karein.");
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (blob) {
        setPhoto({ blob, contentType: "image/jpeg" });
        setPendingEvidenceIds([]);
        setVoiceDraft(null);
        setConfirmationRequired(false);
        resetSubmissionKeys();
      }
      stopCamera();
    }, "image/jpeg", 0.88);
  }

  async function startAudio() {
    setError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error("Is browser mein audio recording available nahi hai.");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data.size) audioChunksRef.current.push(event.data); };
      recorder.onstop = () => {
        const contentType = (recorder.mimeType || "audio/webm").split(";", 1)[0];
        const blob = new Blob(audioChunksRef.current, { type: contentType });
        setAudio({ blob, contentType });
        setPendingEvidenceIds([]);
        setVoiceDraft(null);
        setConfirmationRequired(false);
        resetSubmissionKeys();
        stream.getTracks().forEach((track) => track.stop());
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch (reason: unknown) { setError(errorMessage(reason)); }
  }

  function stopAudio() { recorderRef.current?.stop(); recorderRef.current = null; setRecording(false); }

  function captureLocation() {
    setError("");
    if (!navigator.geolocation) { setError("Is browser mein location available nahi hai."); return; }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocation({ latitude: position.coords.latitude, longitude: position.coords.longitude, accuracyM: Math.max(position.coords.accuracy, 1) });
        setPendingEvidenceIds([]);
        setVoiceDraft(null);
        setConfirmationRequired(false);
        resetSubmissionKeys();
      },
      () => setError("Location nahi mili. GPS permission dekar phir koshish karein."),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 15_000 },
    );
  }

  async function beginVerification() {
    if (!user) return;
    setBusy(true); setError("");
    try { const result = await startIdentityVerification(user.access_token); window.location.assign(result.authorization_url); }
    catch (reason: unknown) { setError(errorMessage(reason)); setBusy(false); }
  }

  function speakText(text: string): void {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = language === "en-IN" ? "en-IN" : "hi-IN";
    utterance.rate = 0.9;
    window.speechSynthesis.speak(utterance);
  }

  async function submitComplaint() {
    if (!user || !photo || !audio || !location || !category) {
      setError("Category, photo, audio aur location zaroori hain.");
      return;
    }
    setBusy(true); setError(""); setMessage("Evidence secure upload ho raha hai…"); setReceipt(null);
    try {
      let evidenceIds = pendingEvidenceIds;
      if (evidenceIds.length > 0) {
        const reviewed = await Promise.all(
          evidenceIds.map((evidenceId) => completeEvidenceUpload(user.access_token, evidenceId)),
        );
        if (reviewed.some((item) => item.status === "rejected")) {
          throw new Error("Evidence review mein accept nahi hui. Nayi photo/audio banayein.");
        }
        if (reviewed.some((item) => item.status === "review_required")) {
          setMessage("Evidence review ke liye save hai. Review complete hone ke baad yahin dobara dabayein.");
          return;
        }
        setMessage("");
      }
      if (evidenceIds.length === 0) {
        const captured: Array<["photo" | "audio", CapturedMedia]> = [["photo", photo], ["audio", audio]];
        let browserReviewPending = false;
        evidenceIds = [];
        for (const [assetType, media] of captured) {
          const idempotencyKey = evidenceIdempotencyKey(assetType);
          const captureSession = await createCaptureSession(user.access_token, assetType, idempotencyKey);
          const upload = await createEvidenceUpload(user.access_token, {
            assetType, contentType: media.contentType, byteSize: media.blob.size, sha256: await sha256Blob(media.blob),
            captureToken: captureSession.capture_token, latitude: location.latitude, longitude: location.longitude,
            accuracyM: location.accuracyM, idempotencyKey,
          });
          await uploadEvidence(upload, media.blob);
          const completed = await completeEvidenceUpload(user.access_token, upload.evidence_asset_id);
          if (completed.status === "rejected") throw new Error("Evidence verify nahi ho saka. Nayi photo/audio banayein.");
          if (completed.status === "review_required") browserReviewPending = true;
          evidenceIds.push(upload.evidence_asset_id);
        }
        setPendingEvidenceIds(evidenceIds);
        if (browserReviewPending) {
          setMessage("Evidence review ke liye save hai. Review complete hone ke baad yahin dobara dabayein.");
          return;
        }
      }

      let resolvedDescription = description.trim();
      if (!resolvedDescription && !voiceDraft) {
        const audioAssetId = evidenceIds[1];
        if (!audioAssetId) throw new Error("Voice note nahi mila.");
        const draft = await createVoiceDraft(user.access_token, {
          audioAssetId,
          language,
          idempotencyKey: voiceDraftKeyRef.current ?? (voiceDraftKeyRef.current = crypto.randomUUID()),
        });
        if (!draft.draft.description) throw new Error("Awaaz se problem samajh nahi aayi. Dobara audio record karein.");
        const nextDraft = {
          description: draft.draft.description,
        };
        setVoiceDraft(nextDraft);
        setDescription(nextDraft.description);
        setConfirmationRequired(true);
        speakText(`Aapne bola: ${nextDraft.description}. Sahi hai toh Haan, submit karein dabayein.`);
        setMessage("Maine aapki baat samjhi. Sun kar sahi lage toh Haan, submit karein dabayein.");
        return;
      }
      if (voiceDraft) {
        resolvedDescription = voiceDraft.description;
      }
      const created = await createComplaint(user.access_token, {
        issueType: category,
        description: resolvedDescription,
        language,
        evidenceAssetIds: evidenceIds,
        idempotencyKey: complaintKeyRef.current ?? (complaintKeyRef.current = crypto.randomUUID()),
      });
      setReceipt(created); setDisclosureSaved(false); setMessage("Aapki shikayat submit ho gayi hai. Ab privacy choice save karein.");
      setPendingEvidenceIds([]); setVoiceDraft(null); setConfirmationRequired(false);
    } catch (reason: unknown) { setError(errorMessage(reason)); setMessage(""); }
    finally { setBusy(false); }
  }

  async function keepDisclosurePrivate() {
    if (!user || !receipt) return;
    setDisclosureBusy(true); setError("");
    try {
      await recordDisclosureConsent(
        user.access_token,
        receipt.complaint_id,
        "verified_citizen",
        `web:${receipt.complaint_id}:disclosure-private`,
      );
      setDisclosureSaved(true);
      setMessage("Aapki shikayat private rakhi gayi hai.");
    } catch {
      setError("Privacy choice save nahi ho saki. Dobara koshish karein.");
    } finally {
      setDisclosureBusy(false);
    }
  }

  if (!isCitizenOidcConfigured()) return <main className="shell narrow-shell"><p className="eyebrow">Citizen filing</p><h1>Sign-in setup baaki hai</h1><p className="lede">Is deployment mein citizen OIDC configured nahi hai. Browser filing activate karne se pehle public OIDC client configure karein.</p><Link className="button button-secondary" href="/">Wapas jaayein</Link></main>;
  if (!user) return <main className="shell narrow-shell"><header className="topbar"><Link className="brand" href="/">AI NETA</Link><Link className="quiet-link" href="/track">Status dekhein</Link></header><section className="page-heading"><p className="eyebrow">Nayi shikayat</p><h1>Pehle sign-in karein</h1><p className="lede">Pehchaan verification ke baad hi complaint, evidence aur location aapke account se judte hain.</p><button className="button button-primary" onClick={() => void beginCitizenSignIn()}>Citizen sign-in</button>{error && <p className="error" role="alert">{error}</p>}</section></main>;
  if (verification !== "verified") return <main className="shell narrow-shell"><header className="topbar"><Link className="brand" href="/">AI NETA</Link><button className="quiet-link link-button" onClick={() => void signOutCitizen()}>Sign out</button></header><section className="page-heading"><p className="eyebrow">Pehchaan verification</p><h1>Identity verify karein</h1><p className="lede">Provider par consent dene ke baad yahan wapas aakar status refresh karein.</p><div className="actions"><button className="button button-primary" disabled={busy} onClick={() => void beginVerification()}>Verification kholein</button><button className="button button-secondary" disabled={busy} onClick={() => window.location.reload()}>Status refresh</button></div>{verification === "rejected" && <p className="error" role="alert">Verification reject hui. Dobara try karein.</p>}{error && <p className="error" role="alert">{error}</p>}</section></main>;

  return <main className="shell narrow-shell" lang={language === "en-IN" ? "en-IN" : "hi"}><header className="topbar"><Link className="brand" href="/">AI NETA</Link><button className="quiet-link link-button" onClick={() => void signOutCitizen()}>Sign out</button></header><section className="page-heading"><p className="eyebrow">Verified citizen filing</p><h1>Apni dikkat record karein</h1><p className="lede">Ek photo, chhota audio note aur current location dein. Type karna zaroori nahi hai—awaaz mein bata sakte hain.</p></section><section className="filing-panel" aria-label="Complaint form"><label htmlFor="complaint-language">Bhasha / Language</label><select id="complaint-language" value={language} onChange={(event) => setLanguage(event.target.value as ComplaintLanguage)}><option value="hi-IN">Hindi</option><option value="en-IN">English</option><option value="hinglish">Hinglish</option></select><span className="field-label">Dikkat kis baare mein hai?</span><div className="category-grid" role="group" aria-label="Complaint category">{catalog?.items.map((item) => <button key={item.code} type="button" className={`category-choice${category === item.code ? " category-choice-selected" : ""}`} aria-pressed={category === item.code} onClick={() => setCategory(item.code)}><span className="category-icon" aria-hidden="true">{item.icon}</span><span>{language === "en-IN" ? item.label_en : item.label_hi}</span></button>)}</div><label htmlFor="description">Apni baat likhein (optional)</label><textarea id="description" value={description} onChange={(event) => { setDescription(event.target.value); setVoiceDraft(null); setConfirmationRequired(false); }} placeholder="Ya sirf audio mein bata dein" rows={3} />{voiceDraft && <div className="readback-card" role="status"><h2>Sun kar confirm karein</h2><p>{voiceDraft.description}</p><button className="button button-secondary" type="button" onClick={() => speakText(`Aapne bola: ${voiceDraft.description}`)}>🔊 Dobara sunayein</button></div>}<div className="capture-grid"><div className="capture-card"><h2>1. Photo</h2>{cameraOpen ? <><video ref={videoRef} className="camera-preview" playsInline muted /><div className="actions"><button className="button button-primary" onClick={capturePhoto}>Photo lein</button><button className="button button-secondary" onClick={stopCamera}>Band karein</button></div></> : <><p>{photo ? "Photo ready hai." : "Gallery se photo nahi; camera se nayi photo lein."}</p><button className="button button-secondary" onClick={() => void openCamera()}>{photo ? "Photo dobara lein" : "Camera kholein"}</button></>}</div><div className="capture-card"><h2>2. Audio</h2><p>{recording ? "Sun raha hoon…" : audio ? "Audio ready hai." : "Apni baat apni awaaz mein batayein."}</p><button className="button button-secondary" onClick={recording ? stopAudio : () => void startAudio()}>{recording ? "Recording rokein" : audio ? "Dobara record karein" : "Audio record karein"}</button></div><div className="capture-card"><h2>3. Location</h2><p>{location ? `Location mil gayi (accuracy ${Math.round(location.accuracyM)}m).` : "Issue ki jagah ka GPS location dein."}</p><button className="button button-secondary" onClick={captureLocation}>{location ? "Location dobara lein" : "Location dein"}</button></div></div><button className="button button-primary full-width" disabled={busy} onClick={() => void submitComplaint()}>{busy ? "Submit ho raha hai…" : voiceDraft && confirmationRequired ? "Haan, submit karein" : !description.trim() ? "Baat samjha kar dikhayein" : "Complaint submit karein"}</button>{message && <p className="success" role="status">{message}</p>}{error && <p className="error" role="alert">{error}</p>}{receipt && <div className="result-card"><p className="result-label">Complaint receipt</p><h2>{receipt.complaint_id}</h2><p>Tracking token: <code>{receipt.tracking_token}</code></p>{!disclosureSaved ? <div className="readback-card" role="group" aria-label="Privacy choice"><h3>Aapki pehchaan private rahe?</h3><p>Hum aapka naam public nahi dikhayenge. Public naam sharing abhi approved policy ke bina band hai.</p><button className="button button-primary" type="button" disabled={disclosureBusy} onClick={() => void keepDisclosurePrivate()}>{disclosureBusy ? "Save ho raha hai…" : "🔒 Haan, private rakhein"}</button></div> : <Link className="button button-secondary" href="/track">Status dekhein</Link>}</div>}</section></main>;
}
