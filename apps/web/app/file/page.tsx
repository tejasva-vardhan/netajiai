"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { User } from "oidc-client-ts";
import {
  CitizenApiError,
  ComplaintReceipt,
  completeEvidenceUpload,
  createCaptureSession,
  createComplaint,
  createEvidenceUpload,
  createVoiceDraft,
  getVerificationStatus,
  recordDisclosureConsent,
  sendConversationTurn,
  sha256Blob,
  startIdentityVerification,
  uploadEvidence,
} from "../../lib/citizen-api";
import {
  beginCitizenRegistration,
  beginCitizenSignIn,
  getCitizenUser,
  isCitizenOidcConfigured,
  signOutCitizen,
} from "../../lib/citizen-auth";

type CapturedMedia = { blob: Blob; contentType: string };
type Coordinates = { latitude: number; longitude: number; accuracyM: number };
type MessageRole = "assistant" | "citizen";
type ChatMessage = { id: string; role: MessageRole; text: string; attachment?: "photo" | "audio" | "location" };
type VerificationProvider = "digilocker" | "temporary";
type VerificationMethod = VerificationProvider;
type GuidedStep = "description" | "location" | "photo" | "voice" | "submit";

const voiceRequiredIssueTypes = new Set(["road", "water", "drainage", "streetlight", "garbage"]);

const welcomeMessage: ChatMessage = {
  id: "welcome",
  role: "assistant",
  text: "Namaste! Main aapki complaint ek-ek step mein taiyaar karunga. Aap likhkar ya bolkar shuru karein—main har agla kaam yahin dikhaunga.",
};

function errorMessage(error: unknown): string {
  if (error instanceof CitizenApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Kuchh galat hua. Dobara koshish karein.";
}

export default function FileComplaintPage() {
  const [user, setUser] = useState<User | null>(null);
  const [verification, setVerification] = useState("loading");
  const [verificationProvider, setVerificationProvider] = useState<VerificationProvider | null>(null);
  const [verificationChoiceOpen, setVerificationChoiceOpen] = useState(false);
  const [language, setLanguage] = useState("hi-IN");
  const [messages, setMessages] = useState<ChatMessage[]>([welcomeMessage]);
  const [messageInput, setMessageInput] = useState("");
  const [conversationSessionId, setConversationSessionId] = useState<string | null>(null);
  const [draftIssueType, setDraftIssueType] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [photo, setPhoto] = useState<CapturedMedia | null>(null);
  const [audio, setAudio] = useState<CapturedMedia | null>(null);
  const [location, setLocation] = useState<Coordinates | null>(null);
  const [photoAssetId, setPhotoAssetId] = useState<string | null>(null);
  const [audioAssetId, setAudioAssetId] = useState<string | null>(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [locationBusy, setLocationBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<ComplaintReceipt | null>(null);
  const [disclosureSaved, setDisclosureSaved] = useState(false);
  const [disclosureBusy, setDisclosureBusy] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const messageInputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const photoEvidenceKeyRef = useRef<string | null>(null);
  const audioEvidenceKeyRef = useRef<string | null>(null);
  const voiceDraftKeyRef = useRef<string | null>(null);
  const complaintKeyRef = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    void getCitizenUser().then((currentUser) => {
      if (!active) return;
      setUser(currentUser);
      if (!currentUser) return;
      void getVerificationStatus(currentUser.access_token)
        .then((status) => {
          if (!active) return;
          setVerificationProvider(status.provider);
          setVerification(status.status);
        })
        .catch((reason: unknown) => { if (active) setError(errorMessage(reason)); });
    }).catch((reason: unknown) => { if (active) setError(errorMessage(reason)); });
    return () => {
      active = false;
      cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
      recorderRef.current?.stop();
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!verificationChoiceOpen) return;
    function closeOnEscape(event: globalThis.KeyboardEvent): void {
      if (event.key === "Escape" && !busy) setVerificationChoiceOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [busy, verificationChoiceOpen]);

  function addMessage(role: MessageRole, text: string, attachment?: ChatMessage["attachment"]): void {
    setMessages((current) => [...current, { id: crypto.randomUUID(), role, text, attachment }]);
  }

  function stopCamera(): void {
    cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
    cameraStreamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraOpen(false);
  }

  async function openCamera(): Promise<void> {
    setError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Is browser mein camera available nahi hai.");
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      cameraStreamRef.current = stream;
      setCameraOpen(true);
      if (videoRef.current) { videoRef.current.srcObject = stream; await videoRef.current.play(); }
    } catch (reason: unknown) { setError(errorMessage(reason)); }
  }

  function capturePhoto(): void {
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
        setPhotoAssetId(null);
        photoEvidenceKeyRef.current = null;
        addMessage("citizen", "Photo attach kiya.", "photo");
        addMessage("assistant", "Photo mil gayi. Ab neeche diya hua agla step karein.");
      }
      stopCamera();
    }, "image/jpeg", 0.88);
  }

  async function startAudio(): Promise<void> {
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
        setAudioAssetId(null);
        audioEvidenceKeyRef.current = null;
        voiceDraftKeyRef.current = null;
        addMessage("citizen", "Voice note attach kiya. Ab ise bhejkar baat samjhaate hain.", "audio");
        stream.getTracks().forEach((track) => track.stop());
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch (reason: unknown) { setError(errorMessage(reason)); }
  }

  function stopAudio(): void {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
  }

  function captureLocation(): void {
    setError("");
    if (!navigator.geolocation) { setError("Is browser mein location available nahi hai."); return; }
    setLocationBusy(true);

    const saveLocation = (position: GeolocationPosition): void => {
      setLocation({ latitude: position.coords.latitude, longitude: position.coords.longitude, accuracyM: Math.max(position.coords.accuracy, 1) });
      setPhotoAssetId(null);
      setAudioAssetId(null);
      setLocationBusy(false);
      addMessage("citizen", "Issue ki location share ki.", "location");
      addMessage("assistant", "Location mil gayi. Ab neeche diya hua agla step karein.");
    };

    const showLocationError = (locationError: GeolocationPositionError): void => {
      setLocationBusy(false);
      if (locationError.code === 1) {
        setError("Location permission deny hui hai. Browser ke address bar mein location allow karke phir koshish karein.");
      } else if (locationError.code === 2) {
        setError("Device location nahi de pa raha. System Location Services aur Wi-Fi on karke phir koshish karein.");
      } else {
        setError("Location milne mein time lag raha hai. System Location Services on karke phir koshish karein.");
      }
    };

    const retryWithHighAccuracy = (locationError: GeolocationPositionError): void => {
      if (locationError.code === 1) { showLocationError(locationError); return; }
      navigator.geolocation.getCurrentPosition(
        saveLocation,
        showLocationError,
        { enableHighAccuracy: true, maximumAge: 0, timeout: 12_000 },
      );
    };

    // Desktop browsers often have a network location before a precise GPS fix.
    navigator.geolocation.getCurrentPosition(
      saveLocation,
      retryWithHighAccuracy,
      { enableHighAccuracy: false, maximumAge: 300_000, timeout: 8_000 },
    );
  }

  async function sendText(): Promise<void> {
    const text = messageInput.trim();
    if (!user || !text || busy) return;
    setMessageInput("");
    setError("");
    addMessage("citizen", text);
    setBusy(true);
    try {
      const response = await sendConversationTurn(user.access_token, {
        text,
        language,
        sessionId: conversationSessionId,
        idempotencyKey: crypto.randomUUID(),
      });
      setConversationSessionId(response.session_id);
      if (response.complaint_draft?.issue_type) {
        setDraftIssueType(response.complaint_draft.issue_type);
        if (response.intent === "filing") setDraftDescription(text);
      }
      addMessage("assistant", response.response_text);
    } catch (reason: unknown) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendText();
    }
  }

  async function sendVoiceNote(): Promise<void> {
    if (!user || !audio || busy) return;
    if (!location) {
      setError("Voice note bhejne se pehle location share karein.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const assetId = audioAssetId ?? await uploadAsset("audio", audio, audioEvidenceKeyRef.current ?? (audioEvidenceKeyRef.current = crypto.randomUUID()));
      setAudioAssetId(assetId);
      const draft = await createVoiceDraft(user.access_token, {
        audioAssetId: assetId,
        language,
        idempotencyKey: voiceDraftKeyRef.current ?? (voiceDraftKeyRef.current = crypto.randomUUID()),
      });
      if (!draft.draft.description || !draft.draft.issue_type) throw new Error("Awaaz se problem samajh nahi aayi. Dobara voice note record karein.");
      setDraftDescription((current) => current || draft.draft.description || "");
      setDraftIssueType(draft.draft.issue_type);
      addMessage("assistant", `Maine suna: “${draft.draft.description}”\n\nBaat note kar li. Ab neeche diya hua agla step karein.`);
    } catch (reason: unknown) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  }

  async function uploadAsset(assetType: "photo" | "audio", media: CapturedMedia, idempotencyKey: string): Promise<string> {
    if (!user || !location) throw new Error("Photo/audio ke saath location zaroori hai.");
    const captureSession = await createCaptureSession(user.access_token, assetType, idempotencyKey);
    const upload = await createEvidenceUpload(user.access_token, {
      assetType,
      contentType: media.contentType,
      byteSize: media.blob.size,
      sha256: await sha256Blob(media.blob),
      captureToken: captureSession.capture_token,
      latitude: location.latitude,
      longitude: location.longitude,
      accuracyM: location.accuracyM,
      idempotencyKey,
    });
    await uploadEvidence(upload, media.blob);
    const completed = await completeEvidenceUpload(user.access_token, upload.evidence_asset_id);
    if (completed.status === "rejected") throw new Error("Evidence verify nahi ho saka. Naya capture karein.");
    if (completed.status !== "verified") throw new Error("Evidence review ke liye save hai. Review complete hone ke baad dobara try karein.");
    return upload.evidence_asset_id;
  }

  function openVerificationChoice(): void {
    setError("");
    setVerificationChoiceOpen(true);
  }

  async function beginVerification(method: VerificationMethod): Promise<void> {
    if (!user) return;
    if (method !== verificationProvider) {
      setError(method === "digilocker" ? "DigiLocker abhi local environment mein connected nahi hai." : "Local placeholder verification available nahi hai.");
      return;
    }
    setBusy(true);
    setError("");
    setVerificationChoiceOpen(false);
    try {
      const result = await startIdentityVerification(user.access_token);
      window.location.assign(result.authorization_url);
    } catch (reason: unknown) { setError(errorMessage(reason)); setBusy(false); }
  }

  async function refreshVerification(): Promise<void> {
    if (!user) return;
    setBusy(true);
    try {
      const status = await getVerificationStatus(user.access_token);
      setVerificationProvider(status.provider);
      setVerification(status.status);
      addMessage("assistant", status.status === "verified" ? "Pehchaan verify ho gayi. Ab apni civic problem batayein." : "Verification abhi complete nahi hui hai.");
    } catch (reason: unknown) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  }

  async function submitComplaint(): Promise<void> {
    const requiresVoice = voiceRequiredIssueTypes.has(draftIssueType);
    if (!user || !photo || !location || !draftIssueType || !draftDescription || (requiresVoice && !audio)) {
      setError(requiresVoice ? "Baat, photo, voice note aur location complete karein." : "Baat, photo aur location complete karein.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const photoId = photoAssetId ?? await uploadAsset("photo", photo, photoEvidenceKeyRef.current ?? (photoEvidenceKeyRef.current = crypto.randomUUID()));
      const evidenceAssetIds = [photoId];
      if (audio) {
        const voiceId = audioAssetId ?? await uploadAsset("audio", audio, audioEvidenceKeyRef.current ?? (audioEvidenceKeyRef.current = crypto.randomUUID()));
        evidenceAssetIds.push(voiceId);
        setAudioAssetId(voiceId);
      }
      const created = await createComplaint(user.access_token, {
        issueType: draftIssueType,
        description: draftDescription,
        language,
        evidenceAssetIds,
        idempotencyKey: complaintKeyRef.current ?? (complaintKeyRef.current = crypto.randomUUID()),
      });
      setPhotoAssetId(photoId);
      setReceipt(created);
      setDisclosureSaved(false);
      addMessage("assistant", `Complaint submit ho gayi hai. Aapka receipt ${created.complaint_id} hai.`);
    } catch (reason: unknown) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  }

  async function keepDisclosurePrivate(): Promise<void> {
    if (!user || !receipt) return;
    setDisclosureBusy(true);
    setError("");
    try {
      await recordDisclosureConsent(user.access_token, receipt.complaint_id, "verified_citizen", `web:${receipt.complaint_id}:disclosure-private`);
      setDisclosureSaved(true);
      addMessage("assistant", "Aapki pehchaan private rakhi gayi hai. Receipt se status kabhi bhi dekhein.");
    } catch (reason: unknown) { setError(errorMessage(reason)); }
    finally { setDisclosureBusy(false); }
  }

  function focusMessageInput(): void {
    messageInputRef.current?.focus();
  }

  function guidedStep(): GuidedStep | null {
    if (verification !== "verified" || receipt) return null;
    if (!draftDescription && !audio) return "description";
    if (!location) return "location";
    if (!draftDescription && audio && !audioAssetId) return "voice";
    if (!photo) return "photo";
    if (voiceRequiredIssueTypes.has(draftIssueType) && !audio) return "voice";
    return "submit";
  }

  if (!isCitizenOidcConfigured()) return <main className="shell narrow-shell"><p className="eyebrow">Citizen filing</p><h1>Sign-in setup baaki hai</h1><p className="lede">Is deployment mein citizen OIDC configured nahi hai.</p><Link className="button button-secondary" href="/">Wapas jaayein</Link></main>;
  if (!user) return <main className="shell narrow-shell"><header className="topbar"><Link className="brand" href="/">AI NETA</Link><Link className="quiet-link" href="/track">Status dekhein</Link></header><section className="page-heading"><p className="eyebrow">Nayi shikayat</p><h1>Account se shuru karein</h1><p className="lede">Login karein ya account banayein. Uske baad identity verification aur complaint filing isi chat mein hogi.</p><div className="actions"><button className="button button-primary" onClick={() => void beginCitizenSignIn().catch((reason: unknown) => setError(errorMessage(reason)))}>Citizen sign-in</button><button className="button button-secondary" onClick={() => void beginCitizenRegistration().catch((reason: unknown) => setError(errorMessage(reason)))}>Create account</button></div>{error && <p className="error" role="alert">{error}</p>}</section></main>;

  const nextGuidedStep = guidedStep();
  const voiceRequired = voiceRequiredIssueTypes.has(draftIssueType);
  const readyToSubmit = Boolean(verification === "verified" && draftIssueType && draftDescription && photo && location && (!voiceRequired || audio) && !receipt);
  return <main className="chat-shell" lang={language === "en-IN" ? "en-IN" : "hi"}>
    <header className="chat-topbar">
      <Link className="brand" href="/">AI NETA</Link>
      <div className="chat-topbar-actions"><label className="language-control" htmlFor="chat-language">{language === "en-IN" ? "Language" : "Bhasha"}<select id="chat-language" value={language} onChange={(event) => setLanguage(event.target.value)}><option value="hi-IN">Hindi</option><option value="en-IN">English</option><option value="hinglish">Hinglish</option></select></label><Link className="quiet-link" href="/track">Status</Link><button className="quiet-link link-button" onClick={() => void signOutCitizen()}>Sign out</button></div>
    </header>
    <section className="chat-panel" aria-label="AI Neta civic conversation">
      <div className="chat-heading"><div><p className="eyebrow">AI Neta assistant</p><h1>Aapki baat, ek hi jagah.</h1><p className="chat-subtitle">Type karein ya bolkar batayein. Main ek samay par sirf agla zaroori step dunga aur complaint bhejne tak aapko saath le kar chalunga.</p></div><span className={`verification-pill ${verification === "verified" ? "verification-verified" : ""}`}>{verification === "verified" ? "Identity verified" : "Verification pending"}</span></div>
      <div className="chat-messages" aria-live="polite">
        {messages.map((message) => <div className={`chat-message chat-message-${message.role}`} key={message.id}><div className="chat-avatar" aria-hidden="true">{message.role === "assistant" ? "✦" : "Aap"}</div><div className="chat-bubble">{message.attachment && <span className="attachment-label">{message.attachment === "photo" ? "📷 Photo" : message.attachment === "audio" ? "🎙️ Voice note" : "📍 Location"}</span>}<p>{message.text}</p></div></div>)}
        {cameraOpen && <div className="chat-camera"><video ref={videoRef} className="camera-preview" playsInline muted /><div className="actions"><button className="button button-primary" onClick={capturePhoto}>Photo lein</button><button className="button button-secondary" onClick={stopCamera}>Band karein</button></div></div>}
        {verification !== "verified" && <div className="chat-action-card"><p className="eyebrow">Pehchaan zaroori hai</p><h2>Complaint se pehle identity verify karein</h2><p>{verificationProvider === "temporary" ? "Abhi local placeholder verification available hai. Government DigiLocker verification approval ke baad connect hogi." : "Identity verification ke baad hi complaint submit hogi."}</p><div className="actions"><button className="button button-primary" disabled={busy || !verificationProvider} onClick={openVerificationChoice}>Verification kholein</button><button className="button button-secondary" disabled={busy} onClick={() => void refreshVerification()}>Status refresh</button></div></div>}
        {nextGuidedStep === "description" && <div className="chat-action-card guided-action-card"><p className="eyebrow">Agla step</p><h2>Apni problem batayein</h2><p>Do line mein likh dein, ya mic dabakar bol dein. Main usse complaint ka draft bana dunga.</p><div className="guided-actions">{recording ? <button className="button button-primary full-width" type="button" onClick={stopAudio}>⏹️ Recording rok dein</button> : <><button className="button button-primary" type="button" onClick={focusMessageInput}>✍️ Problem likhein</button><button className="button button-secondary" type="button" disabled={busy} onClick={() => void startAudio()}>🎙️ Bolkar batayein</button></>}</div></div>}
        {nextGuidedStep === "location" && <div className="chat-action-card guided-action-card"><p className="eyebrow">Agla step</p><h2>Issue ki jagah share karein</h2><p>Isse complaint sahi department tak bhejne mein madad milegi. Aapka location sirf is complaint ke liye use hoga.</p><button className="button button-primary full-width" type="button" disabled={busy || locationBusy} onClick={captureLocation}>{locationBusy ? "📍 Location dhoondh rahe hain…" : "📍 Location share karein"}</button></div>}
        {nextGuidedStep === "photo" && <div className="chat-action-card guided-action-card"><p className="eyebrow">Agla step</p><h2>Issue ki ek photo lein</h2><p>Photo se officer ko problem turant samajhne mein madad milegi.</p><button className="button button-primary full-width" type="button" disabled={busy || cameraOpen} onClick={() => void openCamera()}>📷 Photo lein</button></div>}
        {nextGuidedStep === "voice" && <div className="chat-action-card guided-action-card"><p className="eyebrow">Agla step</p><h2>{recording ? "Awaaz record ho rahi hai" : audio ? "Voice note bhejein" : "Problem ka voice note dein"}</h2><p>{recording ? "Baat poori ho jaaye to recording rok dein." : audio ? "Aapki awaaz ready hai. Isse complaint ke saath attach kar dein." : "Bas 10–20 second mein apni problem apni zubaan mein bata dein."}</p><button className="button button-primary full-width" type="button" disabled={busy && !recording} onClick={recording ? stopAudio : audio ? () => void sendVoiceNote() : () => void startAudio()}>{recording ? "⏹️ Recording rok dein" : audio ? "🎙️ Voice note bhejein" : "🎙️ Voice note record karein"}</button></div>}
        {nextGuidedStep === "submit" && <div className="chat-action-card guided-action-card"><p className="eyebrow">Sab taiyaar hai</p><h2>Complaint bhejne se pehle ek baar dekh lein</h2><p>{voiceRequired ? "Problem, location, photo aur voice note ready hain." : "Problem, location aur photo ready hain."} Sab theek hai to neeche button dabayein.</p><button className="button button-primary full-width" type="button" disabled={!readyToSubmit || busy} onClick={() => void submitComplaint()}>{busy ? "Submit ho raha hai…" : "Complaint submit karein"}</button></div>}
        {receipt && <div className="chat-action-card receipt-card"><p className="eyebrow">Complaint receipt</p><h2>{receipt.complaint_id}</h2><p>Tracking token: <code>{receipt.tracking_token}</code></p>{!disclosureSaved ? <><p>Aapki pehchaan private rakhein?</p><button className="button button-primary" disabled={disclosureBusy} onClick={() => void keepDisclosurePrivate()}>{disclosureBusy ? "Save ho raha hai…" : "🔒 Haan, private rakhein"}</button></> : <Link className="button button-secondary" href="/track">Status dekhein</Link>}</div>}
        <div ref={messagesEndRef} />
      </div>
      <div className="chat-composer">
        <textarea ref={messageInputRef} aria-label="Message" value={messageInput} onChange={(event) => setMessageInput(event.target.value)} onKeyDown={handleInputKeyDown} placeholder="Apni civic problem yahan likhein…" rows={2} disabled={busy} />
        <div className="chat-composer-footer"><button className="button button-primary chat-send" type="button" disabled={busy || !messageInput.trim()} onClick={() => void sendText()}>{busy ? "…" : "Bhejein"}</button></div>
        {error && <p className="error" role="alert">{error}</p>}
        <p className="chat-hint">Enter se message bhejein · Shift + Enter se new line</p>
      </div>
    </section>
    {verificationChoiceOpen && <div className="verification-modal-backdrop" role="presentation" onMouseDown={() => { if (!busy) setVerificationChoiceOpen(false); }}>
      <section className="verification-modal" role="dialog" aria-modal="true" aria-labelledby="verification-modal-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="verification-modal-header"><div><p className="eyebrow">Identity verification</p><h2 id="verification-modal-title">Pehchaan verify karein</h2></div><button className="verification-modal-close" type="button" aria-label="Verification options band karein" onClick={() => setVerificationChoiceOpen(false)} disabled={busy}>×</button></div>
        <p className="verification-modal-copy">Apne liye verification ka tareeqa choose karein.</p>
        <div className="verification-options">
          <button className="verification-option" type="button" disabled={busy || verificationProvider !== "digilocker"} onClick={() => void beginVerification("digilocker")}>
            <span className="verification-option-title">DigiLocker</span>
            <span className="verification-option-copy">{verificationProvider === "digilocker" ? "Approved DigiLocker flow kholein." : "Government approval ke baad available hoga."}</span>
          </button>
          <button className="verification-option" type="button" disabled={busy || verificationProvider !== "temporary"} onClick={() => void beginVerification("temporary")}>
            <span className="verification-option-title">Placeholder verify · local testing</span>
            <span className="verification-option-copy">Local test verification complete karta hai. Yeh government identity proof nahi hai.</span>
          </button>
        </div>
        <p className="verification-modal-note">Local environment mein abhi sirf placeholder option enabled hai.</p>
      </section>
    </div>}
  </main>;
}
