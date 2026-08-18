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
import type { ConversationTurnResponse } from "../../lib/citizen-api";
import { getPublicComplaint, PublicComplaint } from "../../lib/public-api";
import {
  beginCitizenRegistration,
  beginCitizenSignIn,
  getCitizenUser,
  getCitizenUserManager,
  isCitizenOidcConfigured,
  signOutCitizen,
} from "../../lib/citizen-auth";

type CapturedMedia = { blob: Blob; contentType: string };
type Coordinates = { latitude: number; longitude: number; accuracyM: number };
type MessageRole = "assistant" | "citizen";
type ChatMessage = { id: string; role: MessageRole; text: string; attachment?: "photo" | "audio" | "location"; response?: ConversationTurnResponse };
type VerificationProvider = "digilocker" | "temporary";
type VerificationMethod = VerificationProvider;
type GuidedStep = "description" | "location" | "photo" | "photo_review" | "voice" | "submit";
type ConversationMode = "filing" | "general";
type FailedTextTurn = { text: string; language: string; idempotencyKey: string };
type UploadedAssetResult = { id: string; status: "verified" | "review_required" | "rejected" };

const voiceRequiredIssueTypes = new Set(["road", "water", "drainage", "streetlight", "garbage"]);
const issueCategories = [
  { code: "road", icon: "🛣️", label: "सड़क / गड्ढा" },
  { code: "water", icon: "🚰", label: "पानी" },
  { code: "garbage", icon: "🗑️", label: "कचरा" },
  { code: "streetlight", icon: "💡", label: "स्ट्रीट लाइट" },
  { code: "drainage", icon: "🌧️", label: "नाली / जलभराव" },
] as const;
const conversationSessionKey = "aineta.web.conversation_session_id";
const conversationSubjectKey = "aineta.web.conversation_subject";
const conversationModeKey = "aineta.web.conversation_mode";

const welcomeMessage: ChatMessage = {
  id: "welcome",
  role: "assistant",
  text: "Namaste! Main aapki baat sununga—general sawaal, civic complaint, status ya verified yojana ke liye yahin likhein.",
};

function readSessionValue(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeSessionValue(key: string, value: string): boolean {
  try {
    window.sessionStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

function removeSessionValue(key: string): boolean {
  try {
    window.sessionStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof CitizenApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Kuchh galat hua. Dobara koshish karein.";
}

function mergeComplaintDescription(existing: string, additional: string | null): string {
  const current = existing.trim();
  const voice = additional?.trim() ?? "";
  if (!current) return voice;
  if (!voice || current.toLocaleLowerCase().includes(voice.toLocaleLowerCase())) return current;
  return `${current}\n${voice}`;
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
  // A fresh session is general conversation. The router switches to filing
  // only after the citizen asks to report a civic problem (or explicitly
  // starts a new complaint), so verification is not shown prematurely.
  const [conversationMode, setConversationMode] = useState<ConversationMode>("general");
  const [draftIssueType, setDraftIssueType] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [photo, setPhoto] = useState<CapturedMedia | null>(null);
  const [audio, setAudio] = useState<CapturedMedia | null>(null);
  const [location, setLocation] = useState<Coordinates | null>(null);
  const [photoAssetId, setPhotoAssetId] = useState<string | null>(null);
  const [audioAssetId, setAudioAssetId] = useState<string | null>(null);
  const [photoReviewPending, setPhotoReviewPending] = useState(false);
  const [audioReviewPending, setAudioReviewPending] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordingBusy, setRecordingBusy] = useState(false);
  const [locationBusy, setLocationBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<ComplaintReceipt | null>(null);
  const [disclosureSaved, setDisclosureSaved] = useState(false);
  const [disclosureBusy, setDisclosureBusy] = useState(false);
  const [receiptToken, setReceiptToken] = useState("");
  const [receiptStatus, setReceiptStatus] = useState<PublicComplaint | null>(null);
  const [receiptStatusBusy, setReceiptStatusBusy] = useState(false);
  const [receiptStatusError, setReceiptStatusError] = useState("");
  const [sessionExpired, setSessionExpired] = useState(false);
  const [failedTextTurn, setFailedTextTurn] = useState<FailedTextTurn | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const messageInputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const audioStreamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const photoEvidenceKeyRef = useRef<string | null>(null);
  const audioEvidenceKeyRef = useRef<string | null>(null);
  const voiceDraftKeyRef = useRef<string | null>(null);
  const complaintKeyRef = useRef<string | null>(null);
  const verificationResumeKeyRef = useRef<string | null>(null);
  const verificationResumeIdempotencyKeyRef = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    const userManager = getCitizenUserManager();
    const removeUserLoaded = userManager?.events.addUserLoaded((updatedUser) => {
      if (active) setUser(updatedUser);
    });
    const removeSilentRenewError = userManager?.events.addSilentRenewError(() => {
      if (active) {
        setSessionExpired(true);
        setError("Session refresh nahi ho saka. Sign-in dobara karein.");
      }
    });
    void getCitizenUser().then((currentUser) => {
      if (!active) return;
      setUser(currentUser);
      if (!currentUser) return;
      const savedSubject = readSessionValue(conversationSubjectKey);
      if (savedSubject === currentUser.profile.sub) {
        setConversationSessionId(readSessionValue(conversationSessionKey));
        const savedMode = readSessionValue(conversationModeKey);
        if (savedMode === "filing" || savedMode === "general") setConversationMode(savedMode);
      } else {
        removeSessionValue(conversationSessionKey);
        removeSessionValue(conversationModeKey);
        writeSessionValue(conversationSubjectKey, currentUser.profile.sub);
      }
      void getVerificationStatus(currentUser.access_token)
        .then((status) => {
          if (!active) return;
          setVerificationProvider(status.provider);
          setVerification(status.status);
        })
        .catch((reason: unknown) => { if (active) showError(reason); });
    }).catch((reason: unknown) => { if (active) showError(reason); });
    return () => {
      active = false;
      removeUserLoaded?.();
      removeSilentRenewError?.();
      cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
      audioStreamRef.current?.getTracks().forEach((track) => track.stop());
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

  function showError(reason: unknown): void {
    setSessionExpired(reason instanceof CitizenApiError && reason.status === 401);
    setError(errorMessage(reason));
  }

  async function handleSignOut(): Promise<void> {
    try {
      await signOutCitizen();
    } catch (reason: unknown) {
      showError(reason);
    }
  }

  function addMessage(role: MessageRole, text: string, attachment?: ChatMessage["attachment"], response?: ConversationTurnResponse): void {
    setMessages((current) => [...current, { id: crypto.randomUUID(), role, text, attachment, response }]);
  }

  function resetComplaintSubmissionKey(): void {
    complaintKeyRef.current = null;
  }

  function resetFilingState(): void {
    setDraftIssueType("");
    setDraftDescription("");
    setPhoto(null);
    setAudio(null);
    setLocation(null);
    setPhotoAssetId(null);
    setAudioAssetId(null);
    setPhotoReviewPending(false);
    setAudioReviewPending(false);
    photoEvidenceKeyRef.current = null;
    audioEvidenceKeyRef.current = null;
    voiceDraftKeyRef.current = null;
    resetComplaintSubmissionKey();
    verificationResumeKeyRef.current = null;
    verificationResumeIdempotencyKeyRef.current = null;
  }

  function selectIssueType(code: string, label: string): void {
    setDraftIssueType(code);
    resetComplaintSubmissionKey();
    addMessage("citizen", `Problem type: ${label}`);
    addMessage("assistant", "Type mil gaya. Ab neeche diya hua agla step karein.");
  }

  function startNewComplaint(): void {
    resetFilingState();
    setReceipt(null);
    setDisclosureSaved(false);
    setReceiptToken("");
    setReceiptStatus(null);
    setReceiptStatusError("");
    setMessageInput("");
    setFailedTextTurn(null);
    setSessionExpired(false);
    setError("");
    setConversationSessionId(null);
    const sessionCleared = removeSessionValue(conversationSessionKey);
    setConversationMode("filing");
    const modeStored = writeSessionValue(conversationModeKey, "filing");
    setMessages([
      welcomeMessage,
      { id: crypto.randomUUID(), role: "assistant", text: "Nayi complaint shuru karte hain. Apni problem likhein ya bolkar batayein." },
    ]);
    if (!sessionCleared || !modeStored) {
      setError("Nayi complaint shuru ho gayi. Browser session poori tarah reset nahi ho saka; tab band na karein.");
    }
  }

  function stopCamera(): void {
    cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
    cameraStreamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraReady(false);
    setCameraOpen(false);
  }

  async function openCamera(): Promise<void> {
    setError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Is browser mein camera available nahi hai.");
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      cameraStreamRef.current = stream;
      setCameraReady(false);
      setCameraOpen(true);
    } catch (reason: unknown) { showError(reason); }
  }

  useEffect(() => {
    if (!cameraOpen || !cameraStreamRef.current || !videoRef.current) return;
    const video = videoRef.current;
    const stream = cameraStreamRef.current;
    const markReady = (): void => {
      setCameraReady(video.videoWidth > 0 && video.videoHeight > 0);
    };
    video.addEventListener("loadedmetadata", markReady);
    video.addEventListener("canplay", markReady);
    video.srcObject = stream;
    void video.play().then(markReady).catch(() => setError("Camera preview shuru nahi ho saka. Dobara koshish karein."));
    return () => {
      video.removeEventListener("loadedmetadata", markReady);
      video.removeEventListener("canplay", markReady);
      if (video.srcObject === stream) video.srcObject = null;
    };
  }, [cameraOpen]);

  function capturePhoto(): void {
    const video = videoRef.current;
    if (!cameraReady || !video || video.videoWidth === 0 || video.videoHeight === 0) {
      setError("Camera taiyaar nahi hai. Ek pal ruk kar phir koshish karein.");
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    if (!context) {
      setError("Photo taiyaar nahi ho saki. Dobara koshish karein.");
      stopCamera();
      return;
    }
    // toBlob is asynchronous; disable capture immediately so a double click
    // cannot create two evidence attachments from the same frame.
    setCameraReady(false);
    context.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) {
        setError("Photo save nahi ho saki. Dobara koshish karein.");
        stopCamera();
        return;
      }
      setPhoto({ blob, contentType: "image/jpeg" });
      setPhotoAssetId(null);
      setPhotoReviewPending(false);
      photoEvidenceKeyRef.current = null;
      resetComplaintSubmissionKey();
      addMessage("citizen", "Photo attach kiya.", "photo");
      addMessage("assistant", "Photo mil gayi. Ab neeche diya hua agla step karein.");
      stopCamera();
    }, "image/jpeg", 0.88);
  }

  async function startAudio(): Promise<void> {
    setError("");
    if (recordingBusy || recording) return;
    setRecordingBusy(true);
    let stream: MediaStream | null = null;
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error("Is browser mein audio recording available nahi hai.");
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioStreamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data.size) audioChunksRef.current.push(event.data); };
      recorder.onstop = () => {
        const contentType = (recorder.mimeType || "audio/webm").split(";", 1)[0];
        const blob = new Blob(audioChunksRef.current, { type: contentType });
        setAudio({ blob, contentType });
        setAudioAssetId(null);
        setAudioReviewPending(false);
        audioEvidenceKeyRef.current = null;
        voiceDraftKeyRef.current = null;
        resetComplaintSubmissionKey();
        addMessage("citizen", "Voice note attach kiya. Ab ise bhejkar baat samjhaate hain.", "audio");
        stream?.getTracks().forEach((track) => track.stop());
        audioStreamRef.current = null;
        setRecordingBusy(false);
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch (reason: unknown) {
      stream?.getTracks().forEach((track) => track.stop());
      audioStreamRef.current = null;
      setError(errorMessage(reason));
    }
    finally { setRecordingBusy(false); }
  }

  function stopAudio(): void {
    if (recordingBusy) return;
    const recorder = recorderRef.current;
    if (!recorder) return;
    setRecordingBusy(true);
    try {
      recorder.stop();
    } catch (reason: unknown) {
      audioStreamRef.current?.getTracks().forEach((track) => track.stop());
      audioStreamRef.current = null;
      setError(errorMessage(reason));
      setRecordingBusy(false);
    }
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
      setPhotoReviewPending(false);
      setAudioReviewPending(false);
      photoEvidenceKeyRef.current = null;
      audioEvidenceKeyRef.current = null;
      voiceDraftKeyRef.current = null;
      resetComplaintSubmissionKey();
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

  async function sendText(retryTurn?: FailedTextTurn): Promise<void> {
    const text = retryTurn?.text ?? messageInput.trim();
    if (!user || !text || busy) return;
    const idempotencyKey = retryTurn?.idempotencyKey ?? crypto.randomUUID();
    if (!retryTurn) {
      verificationResumeKeyRef.current = null;
      verificationResumeIdempotencyKeyRef.current = null;
      setMessageInput("");
      addMessage("citizen", text);
    }
    setError("");
    setBusy(true);
    try {
      const response = await sendConversationTurn(user.access_token, {
        text,
        language,
        sessionId: conversationSessionId,
        idempotencyKey,
      });
      setFailedTextTurn(null);
      setSessionExpired(false);
      setConversationSessionId(response.session_id);
      const sessionStored = writeSessionValue(conversationSessionKey, response.session_id);
      const subjectStored = writeSessionValue(conversationSubjectKey, user.profile.sub);
      const nextMode: ConversationMode = response.next_action === "start_filing" || response.next_action === "verify_identity" ? "filing" : "general";
      setConversationMode(nextMode);
      const modeStored = writeSessionValue(conversationModeKey, nextMode);
      if (response.intent === "filing") {
        setDraftDescription((current) => mergeComplaintDescription(current, text));
        resetComplaintSubmissionKey();
      }
      if (response.complaint_draft?.issue_type) setDraftIssueType(response.complaint_draft.issue_type);
      addMessage("assistant", response.response_text, undefined, response);
      if (!sessionStored || !subjectStored || !modeStored) {
        setError("Baat ho gayi. Browser session save nahi ho saka; tab band na karein, warna yeh baat dobara dikhani pad sakti hai.");
      }
    } catch (reason: unknown) {
      setFailedTextTurn({ text, language, idempotencyKey });
      showError(reason);
    }
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
      const asset = await uploadAsset("audio", audio, audioEvidenceKeyRef.current ?? (audioEvidenceKeyRef.current = crypto.randomUUID()), audioAssetId);
      setAudioAssetId(asset.id);
      if (asset.status === "review_required") {
        setAudioReviewPending(true);
        setError("Voice note review ke liye save hai. Review complete hone ke baad isi button se status dobara check karein.");
        return;
      }
      if (asset.status === "rejected") {
        setAudio(null);
        setAudioAssetId(null);
        setAudioReviewPending(false);
        audioEvidenceKeyRef.current = null;
        voiceDraftKeyRef.current = null;
        throw new Error("Voice note accept nahi hui. Nayi voice note record karein.");
      }
      setAudioReviewPending(false);
      const draft = await createVoiceDraft(user.access_token, {
        audioAssetId: asset.id,
        language,
        idempotencyKey: voiceDraftKeyRef.current ?? (voiceDraftKeyRef.current = crypto.randomUUID()),
      });
      const issueType = draft.draft.issue_type ?? draftIssueType;
      const description = mergeComplaintDescription(draftDescription, draft.draft.description);
      if (!description || !issueType) {
        setAudio(null);
        setAudioAssetId(null);
        audioEvidenceKeyRef.current = null;
        voiceDraftKeyRef.current = null;
        resetComplaintSubmissionKey();
        throw new Error("Awaaz se problem samajh nahi aayi. Dobara voice note record karein.");
      }
      setDraftDescription(description);
      setDraftIssueType(issueType);
      addMessage("assistant", `Maine suna: “${draft.draft.description ?? description}”\n\nBaat note kar li. Ab neeche diya hua agla step karein.`);
    } catch (reason: unknown) { showError(reason); }
    finally { setBusy(false); }
  }

  async function lookupReceiptStatus(): Promise<void> {
    const token = receiptToken.trim();
    if (!token) {
      setReceiptStatusError("Receipt token likhna zaroori hai.");
      setReceiptStatus(null);
      return;
    }
    setReceiptStatusBusy(true);
    setReceiptStatusError("");
    setReceiptStatus(null);
    try {
      setReceiptStatus(await getPublicComplaint(token));
    } catch (reason: unknown) {
      setReceiptStatusError(errorMessage(reason));
    } finally {
      setReceiptStatusBusy(false);
    }
  }

  async function uploadAsset(
    assetType: "photo" | "audio",
    media: CapturedMedia,
    idempotencyKey: string,
    existingAssetId: string | null,
  ): Promise<UploadedAssetResult> {
    if (!user || !location) throw new Error("Photo/audio ke saath location zaroori hai.");
    if (existingAssetId) {
      try {
        const existing = await completeEvidenceUpload(user.access_token, existingAssetId);
        return { id: existingAssetId, status: existing.status === "verified" ? "verified" : existing.status === "review_required" ? "review_required" : "rejected" };
      } catch (reason: unknown) {
        if (reason instanceof CitizenApiError && reason.status === 404) {
          return { id: existingAssetId, status: "rejected" };
        }
        throw reason;
      }
    }
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
    if (upload.status === "review_required") return { id: upload.evidence_asset_id, status: "review_required" };
    if (upload.status === "verified") return { id: upload.evidence_asset_id, status: "verified" };
    if (upload.status === "rejected") return { id: upload.evidence_asset_id, status: "rejected" };
    if (upload.status === "uploaded") return { id: upload.evidence_asset_id, status: "rejected" };
    await uploadEvidence(upload, media.blob);
    const completed = await completeEvidenceUpload(user.access_token, upload.evidence_asset_id);
    return {
      id: upload.evidence_asset_id,
      status: completed.status === "verified" ? "verified" : completed.status === "review_required" ? "review_required" : "rejected",
    };
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
    const popup = window.open("", "aineta-verification", "popup,width=520,height=720");
    if (!popup) {
      setError("Verification popup block ho gaya. Browser mein popups allow karke phir koshish karein.");
      return;
    }
    setBusy(true);
    setError("");
    setVerificationChoiceOpen(false);
    try {
      const result = await startIdentityVerification(user.access_token);
      popup.location.href = result.authorization_url;
      const deadline = Math.min(
        Date.parse(result.expires_at) || Date.now() + 5 * 60_000,
        Date.now() + 5 * 60_000,
      );
      while (Date.now() < deadline) {
        if (popup.closed) throw new Error("Verification window band ho gaya. Dobara koshish karein.");
        const status = await getVerificationStatus(user.access_token);
        setSessionExpired(false);
        setVerificationProvider(status.provider);
        setVerification(status.status);
        if (status.status === "verified") {
          popup.close();
          await resumeFilingAfterVerification();
          return;
        }
        if (status.status === "rejected") throw new Error("Verification reject hui hai. Dobara koshish karein.");
        await new Promise((resolve) => window.setTimeout(resolve, 5_000));
      }
      throw new Error("Verification ka samay khatam ho gaya. Status refresh karke phir koshish karein.");
    } catch (reason: unknown) {
      popup.close();
      showError(reason);
    } finally {
      setBusy(false);
    }
  }

  async function resumeFilingAfterVerification(): Promise<void> {
    const text = draftDescription.trim();
    if (!user || !conversationSessionId || !text) {
      addMessage("assistant", "Pehchaan verify ho gayi. Ab apni civic problem batayein.");
      return;
    }
    if (verificationResumeKeyRef.current === text && verificationResumeIdempotencyKeyRef.current) return;
    const idempotencyKey = verificationResumeIdempotencyKeyRef.current ?? crypto.randomUUID();
    verificationResumeKeyRef.current = text;
    verificationResumeIdempotencyKeyRef.current = idempotencyKey;
    try {
      const response = await sendConversationTurn(user.access_token, {
        text,
        language,
        sessionId: conversationSessionId,
        idempotencyKey,
      });
      setSessionExpired(false);
      setConversationSessionId(response.session_id);
      const sessionStored = writeSessionValue(conversationSessionKey, response.session_id);
      const subjectStored = writeSessionValue(conversationSubjectKey, user.profile.sub);
      const nextMode: ConversationMode = response.next_action === "start_filing" || response.next_action === "verify_identity" ? "filing" : "general";
      setConversationMode(nextMode);
      const modeStored = writeSessionValue(conversationModeKey, nextMode);
      if (response.complaint_draft?.issue_type) setDraftIssueType(response.complaint_draft.issue_type);
      addMessage("assistant", response.response_text, undefined, response);
      if (!sessionStored || !subjectStored || !modeStored) {
        setError("Pehchaan verify ho gayi. Browser session save nahi ho saka; tab band na karein.");
      }
    } catch (reason: unknown) {
      setFailedTextTurn({ text, language, idempotencyKey });
      showError(reason);
    }
  }

  async function refreshVerification(): Promise<void> {
    if (!user) return;
    setBusy(true);
    try {
      const status = await getVerificationStatus(user.access_token);
      setSessionExpired(false);
      setVerificationProvider(status.provider);
      setVerification(status.status);
      if (status.status === "verified") {
        await resumeFilingAfterVerification();
      } else {
        addMessage("assistant", "Verification abhi complete nahi hui hai.");
      }
    } catch (reason: unknown) { showError(reason); }
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
      const photoAsset = await uploadAsset("photo", photo, photoEvidenceKeyRef.current ?? (photoEvidenceKeyRef.current = crypto.randomUUID()), photoAssetId);
      setPhotoAssetId(photoAsset.id);
      if (photoAsset.status === "review_required") {
        setPhotoReviewPending(true);
        throw new Error("Photo review ke liye save hai. Review complete hone ke baad status dobara check karein.");
      }
      if (photoAsset.status === "rejected") {
        setPhoto(null);
        setPhotoAssetId(null);
        setPhotoReviewPending(false);
        photoEvidenceKeyRef.current = null;
        throw new Error("Photo accept nahi hui. Nayi photo lein.");
      }
      setPhotoReviewPending(false);
      const evidenceAssetIds = [photoAsset.id];
      if (audio) {
        const audioAsset = await uploadAsset("audio", audio, audioEvidenceKeyRef.current ?? (audioEvidenceKeyRef.current = crypto.randomUUID()), audioAssetId);
        setAudioAssetId(audioAsset.id);
        if (audioAsset.status === "review_required") {
          setAudioReviewPending(true);
          throw new Error("Voice note review ke liye save hai. Review complete hone ke baad status dobara check karein.");
        }
        if (audioAsset.status === "rejected") {
          setAudio(null);
          setAudioAssetId(null);
          setAudioReviewPending(false);
          audioEvidenceKeyRef.current = null;
          throw new Error("Voice note accept nahi hui. Nayi voice note record karein.");
        }
        setAudioReviewPending(false);
        evidenceAssetIds.push(audioAsset.id);
      }
      const created = await createComplaint(user.access_token, {
        issueType: draftIssueType,
        description: draftDescription,
        language,
        evidenceAssetIds,
        idempotencyKey: complaintKeyRef.current ?? (complaintKeyRef.current = crypto.randomUUID()),
      });
      setReceipt(created);
      setDisclosureSaved(false);
      addMessage("assistant", `Complaint submit ho gayi hai. Aapka receipt ${created.complaint_id} hai.`);
    } catch (reason: unknown) { showError(reason); }
    finally { setBusy(false); }
  }

  async function refreshPhotoReview(): Promise<void> {
    if (!user || !photoAssetId || busy) return;
    setBusy(true);
    setError("");
    try {
      const completed = await completeEvidenceUpload(user.access_token, photoAssetId);
      if (completed.status === "verified") {
        setPhotoReviewPending(false);
        return;
      }
      if (completed.status === "review_required") {
        setError("Photo abhi review mein hai. Review complete hone ke baad phir status check karein.");
        return;
      }
      setPhoto(null);
      setPhotoAssetId(null);
      setPhotoReviewPending(false);
      photoEvidenceKeyRef.current = null;
      resetComplaintSubmissionKey();
      setError("Photo accept nahi hui. Nayi photo lein.");
    } catch (reason: unknown) {
      showError(reason);
    } finally {
      setBusy(false);
    }
  }

  async function keepDisclosurePrivate(): Promise<void> {
    if (!user || !receipt) return;
    setDisclosureBusy(true);
    setError("");
    try {
      await recordDisclosureConsent(user.access_token, receipt.complaint_id, "verified_citizen", `web:${receipt.complaint_id}:disclosure-private`);
      setDisclosureSaved(true);
      addMessage("assistant", "Aapki pehchaan private rakhi gayi hai. Receipt se status kabhi bhi dekhein.");
    } catch (reason: unknown) { showError(reason); }
    finally { setDisclosureBusy(false); }
  }

  function focusMessageInput(): void {
    messageInputRef.current?.focus();
  }

  function guidedStep(): GuidedStep | null {
    if (verification !== "verified" || receipt || conversationMode !== "filing") return null;
    if (!draftDescription && !audio) return "description";
    if (!draftIssueType && !audio) return "description";
    // Voice-first filing still needs the server-bound location before the
    // audio upload/transcription can begin.
    if (!location) return "location";
    if (audio && (!draftDescription || !draftIssueType)) return "voice";
    if (photoReviewPending) return "photo_review";
    if (audioReviewPending) return "voice";
    if (!photo) return "photo";
    if (voiceRequiredIssueTypes.has(draftIssueType) && !audio) return "voice";
    return "submit";
  }

  if (!isCitizenOidcConfigured()) return <main className="shell narrow-shell"><p className="eyebrow">Citizen filing</p><h1>Sign-in setup baaki hai</h1><p className="lede">Is deployment mein citizen OIDC configured nahi hai.</p><Link className="button button-secondary" href="/">Wapas jaayein</Link></main>;
  if (!user) return <main className="shell narrow-shell"><header className="topbar"><Link className="brand" href="/">AI NETA</Link><Link className="quiet-link" href="/track">Status dekhein</Link></header><section className="page-heading"><p className="eyebrow">Nayi shikayat</p><h1>Account se shuru karein</h1><p className="lede">Login karein ya account banayein. Uske baad identity verification aur complaint filing isi chat mein hogi.</p><div className="actions"><button className="button button-primary" onClick={() => void beginCitizenSignIn().catch((reason: unknown) => setError(errorMessage(reason)))}>Citizen sign-in</button><button className="button button-secondary" onClick={() => void beginCitizenRegistration().catch((reason: unknown) => setError(errorMessage(reason)))}>Create account</button></div>{error && <p className="error" role="alert">{error}</p>}</section></main>;

  const nextGuidedStep = guidedStep();
  const voiceRequired = voiceRequiredIssueTypes.has(draftIssueType);
  const readyToSubmit = Boolean(verification === "verified" && draftIssueType && draftDescription && photo && location && (!voiceRequired || audio) && !photoReviewPending && !audioReviewPending && !receipt);
  const latestMessage = messages[messages.length - 1];
  const latestResponseId = latestMessage?.response ? latestMessage.id : null;
  return <main className="chat-shell" lang={language === "en-IN" ? "en-IN" : "hi"}>
    <header className="chat-topbar">
      <Link className="brand" href="/">AI NETA</Link>
      <div className="chat-topbar-actions"><label className="language-control" htmlFor="chat-language">{language === "en-IN" ? "Language" : "Bhasha"}<select id="chat-language" value={language} onChange={(event) => setLanguage(event.target.value)}><option value="hi-IN">Hindi</option><option value="en-IN">English</option><option value="hinglish">Hinglish</option></select></label><Link className="quiet-link" href="/track">Status</Link><button className="quiet-link link-button" onClick={() => void handleSignOut()}>Sign out</button></div>
    </header>
    <section className="chat-panel" aria-label="AI Neta civic conversation">
      <div className="chat-heading"><div><p className="eyebrow">AI Neta assistant</p><h1>Aapki baat, ek hi jagah.</h1><p className="chat-subtitle">Type karein ya bolkar batayein. Main ek samay par sirf agla zaroori step dunga aur complaint bhejne tak aapko saath le kar chalunga.</p></div><span className={`verification-pill ${verification === "verified" ? "verification-verified" : ""}`}>{verification === "verified" ? "Identity verified" : "Verification pending"}</span></div>
      <div className="chat-messages" aria-live="polite">
        {messages.map((message) => <div className={`chat-message chat-message-${message.role}`} key={message.id}><div className="chat-avatar" aria-hidden="true">{message.role === "assistant" ? "✦" : "Aap"}</div><div className="chat-bubble">{message.attachment && <span className="attachment-label">{message.attachment === "photo" ? "📷 Photo" : message.attachment === "audio" ? "🎙️ Voice note" : "📍 Location"}</span>}<p>{message.text}</p>{message.response && message.id === latestResponseId && <ConversationHandoff response={message.response} receiptToken={receiptToken} receiptStatus={receiptStatus} receiptStatusBusy={receiptStatusBusy} receiptStatusError={receiptStatusError} onReceiptTokenChange={setReceiptToken} onLookupReceipt={() => void lookupReceiptStatus()} />}</div></div>)}
        {cameraOpen && <div className="chat-camera"><video ref={videoRef} className="camera-preview" aria-label="Camera preview" playsInline muted />{!cameraReady && <p className="camera-status" role="status">Camera taiyaar ho rahi hai…</p>}<div className="actions"><button className="button button-primary" disabled={!cameraReady || busy} onClick={capturePhoto}>Photo lein</button><button className="button button-secondary" disabled={busy} onClick={stopCamera}>Band karein</button></div></div>}
        {conversationMode === "filing" && verification !== "verified" && <div className="chat-action-card"><p className="eyebrow">Pehchaan zaroori hai</p><h2>Complaint se pehle identity verify karein</h2><p>{verificationProvider === "temporary" ? "Abhi local placeholder verification available hai. Government DigiLocker verification approval ke baad connect hogi." : "Identity verification ke baad hi complaint submit hogi."}</p><div className="actions"><button className="button button-primary" disabled={busy || !verificationProvider} onClick={openVerificationChoice}>Verification kholein</button><button className="button button-secondary" disabled={busy} onClick={() => void refreshVerification()}>Status refresh</button></div></div>}
        {nextGuidedStep === "description" && <div className="chat-action-card guided-action-card"><p className="eyebrow">Agla step</p><h2>{draftDescription && !draftIssueType ? "Problem ka type batayein" : "Apni problem batayein"}</h2><p>{draftDescription && !draftIssueType ? "Neeche se type choose karein, ya ek shabd mein likh dein." : "Do line mein likh dein, ya mic dabakar bol dein. Main usse complaint ka draft bana dunga."}</p>{draftDescription && !draftIssueType && <div className="category-grid">{issueCategories.map((category) => <button key={category.code} className="category-choice" type="button" onClick={() => selectIssueType(category.code, category.label)}><span className="category-icon" aria-hidden="true">{category.icon}</span><span>{category.label}</span></button>)}</div>}<div className="guided-actions">{recording ? <button className="button button-primary full-width" type="button" disabled={recordingBusy} onClick={stopAudio}>⏹️ Recording rok dein</button> : <><button className="button button-primary" type="button" onClick={focusMessageInput}>✍️ Problem likhein</button><button className="button button-secondary" type="button" disabled={busy || recordingBusy} onClick={() => void startAudio()}>🎙️ Bolkar batayein</button></>}</div></div>}
        {nextGuidedStep === "location" && <div className="chat-action-card guided-action-card"><p className="eyebrow">Agla step</p><h2>Issue ki jagah share karein</h2><p>Isse complaint sahi department tak bhejne mein madad milegi. Aapka location sirf is complaint ke liye use hoga.</p><button className="button button-primary full-width" type="button" disabled={busy || locationBusy} onClick={captureLocation}>{locationBusy ? "📍 Location dhoondh rahe hain…" : "📍 Location share karein"}</button></div>}
        {nextGuidedStep === "photo" && <div className="chat-action-card guided-action-card"><p className="eyebrow">Agla step</p><h2>Issue ki ek photo lein</h2><p>Photo se officer ko problem turant samajhne mein madad milegi.</p><button className="button button-primary full-width" type="button" disabled={busy || cameraOpen} onClick={() => void openCamera()}>📷 Photo lein</button></div>}
        {nextGuidedStep === "photo_review" && <div className="chat-action-card guided-action-card"><p className="eyebrow">Photo review</p><h2>Photo ki jaanch chal rahi hai</h2><p>Photo save hai. Review complete hone par isi screen se status check karein—dobara photo lene ki zaroorat nahi.</p><button className="button button-primary full-width" type="button" disabled={busy} onClick={() => void refreshPhotoReview()}>{busy ? "Status dekha ja raha hai…" : "📷 Photo status dobara dekhein"}</button></div>}
        {nextGuidedStep === "voice" && <div className="chat-action-card guided-action-card"><p className="eyebrow">Agla step</p><h2>{recording ? "Awaaz record ho rahi hai" : audioReviewPending ? "Voice note ki jaanch chal rahi hai" : audio ? "Voice note bhejein" : "Problem ka voice note dein"}</h2><p>{recording ? "Baat poori ho jaaye to recording rok dein." : audioReviewPending ? "Voice note save hai. Review complete hone par status dobara check karein." : audio ? "Aapki awaaz ready hai. Isse complaint ke saath attach kar dein." : "Bas 10–20 second mein apni problem apni zubaan mein bata dein."}</p><button className="button button-primary full-width" type="button" disabled={recordingBusy || (busy && !recording)} onClick={recording ? stopAudio : audio ? () => void sendVoiceNote() : () => void startAudio()}>{recording ? "⏹️ Recording rok dein" : audioReviewPending ? "🎙️ Voice status dobara dekhein" : audio ? "🎙️ Voice note bhejein" : "🎙️ Voice note record karein"}</button></div>}
        {nextGuidedStep === "submit" && <div className="chat-action-card guided-action-card"><p className="eyebrow">Sab taiyaar hai</p><h2>Complaint bhejne se pehle ek baar dekh lein</h2><p>{voiceRequired ? "Problem, location, photo aur voice note ready hain." : "Problem, location aur photo ready hain."} Sab theek hai to neeche button dabayein.</p><button className="button button-primary full-width" type="button" disabled={!readyToSubmit || busy} onClick={() => void submitComplaint()}>{busy ? "Submit ho raha hai…" : "Complaint submit karein"}</button></div>}
        {receipt && <div className="chat-action-card receipt-card"><p className="eyebrow">Complaint receipt</p><h2>{receipt.complaint_id}</h2><p>Tracking token: <code>{receipt.tracking_token}</code></p>{!disclosureSaved ? <><p>Aapki pehchaan private rakhein?</p><button className="button button-primary" disabled={disclosureBusy} onClick={() => void keepDisclosurePrivate()}>{disclosureBusy ? "Save ho raha hai…" : "🔒 Haan, private rakhein"}</button></> : <div className="actions"><Link className="button button-secondary" href={`/track?token=${encodeURIComponent(receipt.tracking_token)}`}>Status dekhein</Link><button className="button button-secondary" type="button" onClick={startNewComplaint}>Nayi complaint</button></div>}</div>}
        <div ref={messagesEndRef} />
      </div>
      <div className="chat-composer">
        <textarea ref={messageInputRef} aria-label="Message" value={messageInput} onChange={(event) => setMessageInput(event.target.value)} onKeyDown={handleInputKeyDown} placeholder="Apni civic problem yahan likhein…" rows={2} disabled={busy} />
        <div className="chat-composer-footer"><button className="button button-primary chat-send" type="button" disabled={busy || !messageInput.trim()} onClick={() => void sendText()}>{busy ? "…" : "Bhejein"}</button></div>
        {error && <div className="error-block" role="alert"><p className="error">{error}</p>{failedTextTurn && <button className="button button-secondary" type="button" disabled={busy} onClick={() => void sendText(failedTextTurn)}>Dobara bhejein</button>}{sessionExpired && <button className="button button-secondary" type="button" onClick={() => void handleSignOut()}>Sign-in dobara karein</button>}</div>}
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

function ConversationHandoff({
  response,
  receiptToken,
  receiptStatus,
  receiptStatusBusy,
  receiptStatusError,
  onReceiptTokenChange,
  onLookupReceipt,
}: {
  response: ConversationTurnResponse;
  receiptToken: string;
  receiptStatus: PublicComplaint | null;
  receiptStatusBusy: boolean;
  receiptStatusError: string;
  onReceiptTokenChange: (value: string) => void;
  onLookupReceipt: () => void;
}) {
  const hasReceiptHandoff = response.next_action === "provide_receipt";
  const hasSchemeSources = response.scheme_sources.length > 0;
  if (!hasReceiptHandoff && !hasSchemeSources) return null;

  return <div className="conversation-handoff">
    {hasReceiptHandoff && <form className="conversation-handoff-form" onSubmit={(event) => { event.preventDefault(); onLookupReceipt(); }}>
      <label htmlFor={`receipt-${response.response_id}`}>Receipt token</label>
      <div className="conversation-handoff-controls">
        <input id={`receipt-${response.response_id}`} value={receiptToken} onChange={(event) => onReceiptTokenChange(event.target.value)} placeholder="Receipt token yahan likhein" autoComplete="off" spellCheck={false} />
        <button className="button button-primary" type="submit" disabled={receiptStatusBusy}>{receiptStatusBusy ? "Dekh rahe hain…" : "Status dekhein"}</button>
      </div>
      {receiptStatusError && <p className="error" role="alert">{receiptStatusError}</p>}
      {receiptStatus && <div className="conversation-handoff-result" role="status"><strong>{receiptStatus.status.replaceAll("_", " ")}</strong><span>{receiptStatus.issue_type ?? "Civic issue"}</span><span>{receiptStatus.execution_zone_state.replaceAll("_", " ")}</span></div>}
    </form>}
    {hasSchemeSources && <div className="conversation-sources"><p className="eyebrow">Verified source</p><ul>{response.scheme_sources.map((source) => <li key={source.source_id}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a></li>)}</ul></div>}
  </div>;
}
