"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { API_BASE } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";
const CHAT_API = `${API_BASE}/chat`;
const CHAT_VOICE_API = `${API_BASE}/chat/voice`;
const CHAT_PHOTO_API = `${API_BASE}/chat/photo`;
/** Must match bot.py MAP_LOCATION_CONFIRM_TOKEN — sent when user taps Confirm on the map. */
const MAP_LOCATION_CONFIRM_TOKEN = "__AINETA_MAP_CONFIRM__";
const APP_TITLE = "AI NETA";
const CHAT_DRAFT_STORAGE_KEY = "aineta_chat_draft";

const WELCOME_MESSAGE =
  "नमस्ते! मैं AI नेता हूँ। आपकी लोकेशन के आधार पर शिकायत सही अधिकारियों तक पहुँचेगी। सड़क, पानी, बिजली, सफाई जैसी कोई भी समस्या बताइए।";

type Message = {
  role: "user" | "bot";
  content: string;
};

const LocationMap = dynamic(() => import("../components/LocationMap"), {
  ssr: false,
});

function ChatHeader({
  subtitle,
  onNewChat,
}: {
  subtitle?: string;
  onNewChat: () => void;
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-emerald-700 bg-emerald-600 text-white shadow-md">
      <div className="mx-auto flex w-full max-w-2xl items-center justify-between px-3 py-2">
        <Link
          href="/"
          className="rounded-md px-2 py-1 text-sm font-medium text-emerald-50 hover:bg-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
        >
          ← Home
        </Link>
        <h1 suppressHydrationWarning className="text-base font-semibold tracking-tight sm:text-lg">
          {APP_TITLE}
        </h1>
        <button
          type="button"
          onClick={onNewChat}
          className="rounded-md bg-white/10 px-2.5 py-1 text-sm font-medium text-white hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
        >
          ➕ New Chat
        </button>
      </div>
      {subtitle ? (
        <p className="truncate px-3 pb-2 text-center text-xs text-emerald-100/95">{subtitle}</p>
      ) : null}
    </header>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"} px-3 py-1.5`}
    >
      <div
        className={`max-w-[85%] sm:max-w-[75%] rounded-2xl px-4 py-2.5 shadow-sm ${
          isUser
            ? "bg-emerald-500 text-white rounded-br-md"
            : "bg-white text-gray-800 rounded-bl-md border border-gray-200"
        }`}
      >
        <p className="text-sm sm:text-base whitespace-pre-wrap break-words">
          {message.content}
        </p>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex justify-start px-3 py-1.5">
      <div className="bg-white rounded-2xl rounded-bl-md px-4 py-3 border border-gray-200 shadow-sm">
        <span className="text-gray-500 text-sm">typing...</span>
      </div>
    </div>
  );
}

function ChatInput({
  onSend,
  disabled,
  photoUploadEnabled,
  onPhotoFile,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
  photoUploadEnabled: boolean;
  onPhotoFile: (file: File) => void;
}) {
  const [input, setInput] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [selectedPhoto, setSelectedPhoto] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setInput("");
    inputRef.current?.focus();
  };

  const handleToggleRecording = async () => {
    if (disabled) return;

    // Stop recording
    if (isRecording && mediaRecorderRef.current) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      return;
    }

    // Start recording
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert("Microphone not supported in this browser.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });

        // Stop all tracks so mic is released
        stream.getTracks().forEach((track) => track.stop());

        if (blob.size === 0) return;

        // Dispatch a custom event so parent can upload it
        const customEvent = new CustomEvent("voice-message-recorded", {
          detail: blob,
        });
        window.dispatchEvent(customEvent);
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error("Error starting recording:", err);
      alert("Could not access microphone.");
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f || disabled) return;
    setSelectedPhoto(f);
    setPhotoPreview(URL.createObjectURL(f));
  };

  const handleSendSelectedPhoto = () => {
    if (!selectedPhoto || disabled) return;
    onPhotoFile(selectedPhoto);
    setSelectedPhoto(null);
    if (photoPreview) URL.revokeObjectURL(photoPreview);
    setPhotoPreview(null);
  };

  useEffect(() => {
    return () => {
      if (photoPreview) URL.revokeObjectURL(photoPreview);
    };
  }, [photoPreview]);

  return (
    <div className="sticky bottom-0 bg-gray-100 border-t border-gray-200">
      {selectedPhoto && photoPreview && (
        <div className="mx-3 mt-2 flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-2">
          <img
            src={photoPreview}
            alt="Selected upload preview"
            className="h-14 w-14 rounded object-cover border border-gray-200"
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs text-gray-700">{selectedPhoto.name}</p>
            <p className="text-[11px] text-gray-500">Preview before sending</p>
          </div>
          <button
            type="button"
            onClick={handleSendSelectedPhoto}
            disabled={disabled}
            className="rounded-md bg-emerald-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            Send Photo
          </button>
        </div>
      )}
      <form
        onSubmit={handleSubmit}
        className="flex gap-2 p-3"
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          aria-hidden
          onChange={handleFileChange}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || !photoUploadEnabled}
          title={photoUploadEnabled ? "Upload photo" : "Photo upload available after bot asks for a photo"}
          aria-label="Upload photo"
          className="rounded-full px-3 py-2.5 text-sm sm:text-base font-medium border border-gray-400 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          📷
        </button>
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="अपनी शिकायत लिखें..."
          disabled={disabled}
          className="flex-1 rounded-full border border-gray-300 bg-white px-4 py-2.5 text-sm sm:text-base focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent disabled:opacity-60"
        />
        <button
          type="button"
          onClick={handleToggleRecording}
          disabled={disabled}
          aria-label={isRecording ? "Stop recording" : "Record voice"}
          className={`rounded-full px-3 py-2.5 text-sm sm:text-base font-medium border ${
            isRecording
              ? "bg-red-600 text-white border-red-700"
              : "bg-white text-emerald-700 border-emerald-600"
          } hover:bg-emerald-50 disabled:opacity-60 disabled:cursor-not-allowed transition-colors`}
        >
          {isRecording ? "Stop" : "🎤"}
        </button>
        <button
          type="submit"
          disabled={disabled || !input.trim()}
          className="rounded-full bg-emerald-600 px-4 py-2.5 text-white font-medium text-sm sm:text-base hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
        >
          Send
        </button>
      </form>
    </div>
  );
}

/** True when the bot is asking for location (backend field or message text). */
function botIsAskingForLocation(
  field: string | null | undefined,
  reply: string
): boolean {
  if (field === "location") return true;
  const t = reply.toLowerCase();
  return (
    t.includes("confirm location") ||
    t.includes("openstreetmap") ||
    t.includes("नक्शे") ||
    t.includes("exact location") ||
    t.includes("सटीक स्थान") ||
    (t.includes("location") && t.includes("mohalla"))
  );
}

type GeoStatus = "pending" | "ready" | "denied" | "unsupported";

export default function ChatPage() {
  const router = useRouter();
  const { isReady, isLoggedIn, authFetch } = useAuth({
    redirectOnUnauthorizedTo: "/login",
  });
  const [geoStatus, setGeoStatus] = useState<GeoStatus>("pending");
  const [geoError, setGeoError] = useState<string | null>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [expectPhotoUpload, setExpectPhotoUpload] = useState(false);
  const [showLocationMap, setShowLocationMap] = useState(false);
  const [latitude, setLatitude] = useState(25.432);
  const [longitude, setLongitude] = useState(77.6644);
  const [locationConfirmed, setLocationConfirmed] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const draftLoadedRef = useRef(false);

  const requestLocation = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setGeoStatus("unsupported");
      setGeoError("This browser does not support location.");
      return;
    }
    setGeoStatus("pending");
    setGeoError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        setLatitude(lat);
        setLongitude(lng);
        setGeoStatus("ready");
        if (!draftLoadedRef.current) {
          setMessages([{ role: "bot", content: WELCOME_MESSAGE }]);
        }
      },
      (err) => {
        setGeoStatus("denied");
        setGeoError(err.message || "Location permission denied.");
      },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }
    );
  }, []);

  useEffect(() => {
    requestLocation();
  }, [requestLocation]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(CHAT_DRAFT_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        const safe = parsed.filter(
          (m): m is Message =>
            !!m &&
            typeof m === "object" &&
            (m.role === "user" || m.role === "bot") &&
            typeof m.content === "string"
        );
        if (safe.length > 0) {
          setMessages(safe);
          draftLoadedRef.current = true;
        }
      }
    } catch {
      window.localStorage.removeItem(CHAT_DRAFT_STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(CHAT_DRAFT_STORAGE_KEY, JSON.stringify(messages));
    } catch {
      // Ignore storage errors (private mode / quota, etc.)
    }
  }, [messages]);

  const headerSubtitle =
    geoStatus === "ready"
      ? `Location on · ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`
      : undefined;

  const applyBotResponseMeta = useCallback(
    (
      data: {
        field?: string | null;
        type?: string;
      },
      reply: string
    ) => {
      const asksLocation = botIsAskingForLocation(data.field ?? undefined, reply);
      setShowLocationMap(asksLocation);
      if (asksLocation) setLocationConfirmed(false);

      if (data.field === "photo_consent" || data.field === "photo_path")
        setExpectPhotoUpload(true);
      else if (data.type === "complaint_summary" || data.type === "complaint_registered")
        setExpectPhotoUpload(false);
    },
    []
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, isLoading]);

  const sendChatRequest = useCallback(
    async (url: string, init: RequestInit, withJsonContentType: boolean): Promise<Response> => {
      const headers = withJsonContentType
        ? ({ "Content-Type": "application/json", ...(init.headers as Record<string, string> | undefined) } as HeadersInit)
        : init.headers;
      if (!isLoggedIn) {
        router.replace("/login");
        throw new Error("Please login to continue.");
      }
      return authFetch(url, { ...init, headers });
    },
    [authFetch, isLoggedIn, router]
  );

  useEffect(() => {
    if (!isReady) return;
    if (!isLoggedIn) {
      router.replace("/login");
    }
  }, [isLoggedIn, isReady, router]);

  const confirmMapLocation = useCallback(async (lat: number, lng: number) => {
    if (geoStatus !== "ready") return;
    setLatitude(lat);
    setLongitude(lng);
    setShowLocationMap(false);
    setIsLoading(true);
    try {
      const res = await sendChatRequest(CHAT_API, {
        method: "POST",
        body: JSON.stringify({
          user_id: "web_citizen_1",
          phone: "9876543210",
          message: MAP_LOCATION_CONFIRM_TOKEN,
          latitude: lat,
          longitude: lng,
        }),
      }, true);
      if (!res.ok) {
        if (res.status === 401) throw new Error("Session expired. Please login again.");
        const errText = await res.text();
        throw new Error(errText || `HTTP ${res.status}`);
      }
      const data = await res.json();
      const reply = typeof data.reply === "string" ? data.reply : String(data.reply ?? "");
      applyBotResponseMeta(data, reply);
      setLocationConfirmed(true);
      setMessages((prev) => [
        ...prev,
        {
          role: "user",
          content: `📍 Map pin saved (${lat.toFixed(5)}, ${lng.toFixed(5)})`,
        },
        { role: "bot", content: reply },
      ]);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "कुछ गलत हो गया। कृपया पुनः प्रयास करें।";
      setMessages((prev) => [
        ...prev,
        { role: "bot", content: `त्रुटि (map): ${errorMessage}` },
      ]);
      setShowLocationMap(true);
    } finally {
      setIsLoading(false);
    }
  }, [geoStatus, applyBotResponseMeta, sendChatRequest]);

  const sendMessage = useCallback(async (userText: string) => {
    if (geoStatus !== "ready") return;
    setShowLocationMap(false);
    setMessages((prev) => [...prev, { role: "user", content: userText }]);
    setIsLoading(true);

    try {
      const res = await sendChatRequest(CHAT_API, {
        method: "POST",
        body: JSON.stringify({
          user_id: "web_citizen_1",
          phone: "9876543210",
          message: userText,
          latitude,
          longitude,
        }),
      }, true);

      if (!res.ok) {
        if (res.status === 401) throw new Error("Session expired. Please login again.");
        const errText = await res.text();
        throw new Error(errText || `HTTP ${res.status}`);
      }

      const data = await res.json();
      const reply = typeof data.reply === "string" ? data.reply : String(data.reply ?? "");
      applyBotResponseMeta(data, reply);
      setMessages((prev) => [...prev, { role: "bot", content: reply }]);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "कुछ गलत हो गया। कृपया पुनः प्रयास करें।";
      setMessages((prev) => [
        ...prev,
        { role: "bot", content: `त्रुटि: ${errorMessage}` },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [geoStatus, latitude, longitude, sendChatRequest, applyBotResponseMeta]);

  // Voice message handler: uploads audio blob to /chat/voice
  const handleVoiceMessage = useCallback(async (audioBlob: Blob) => {
    if (geoStatus !== "ready") return;
    setShowLocationMap(false);
    setIsLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", audioBlob, "voice.webm");
      formData.append("user_id", "web_citizen_1");
      formData.append("phone", "9876543210");
      formData.append("latitude", String(latitude));
      formData.append("longitude", String(longitude));

      const res = await sendChatRequest(CHAT_VOICE_API, {
        method: "POST",
        body: formData,
      }, false);

      if (!res.ok) {
        if (res.status === 401) throw new Error("Session expired. Please login again.");
        const errText = await res.text();
        throw new Error(errText || `HTTP ${res.status}`);
      }

      const data = await res.json();
      const transcript =
        typeof data.transcript === "string" && data.transcript.trim().length > 0
          ? data.transcript
          : "🎤 Voice message";
      const reply =
        typeof data.reply === "string" ? data.reply : String(data.reply ?? "");

      applyBotResponseMeta(data, reply);

      setMessages((prev) => [
        ...prev,
        { role: "user", content: transcript },
        { role: "bot", content: reply },
      ]);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "कुछ गलत हो गया। कृपया पुनः प्रयास करें।";
      setMessages((prev) => [
        ...prev,
        { role: "bot", content: `त्रुटि (voice): ${errorMessage}` },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [geoStatus, latitude, longitude, applyBotResponseMeta, sendChatRequest]);

  // Listen for the custom event fired by ChatInput when recording completes
  useEffect(() => {
    const listener = (event: Event) => {
      const custom = event as CustomEvent<Blob>;
      if (custom.detail) {
        void handleVoiceMessage(custom.detail);
      }
    };

    window.addEventListener("voice-message-recorded", listener as EventListener);
    return () => {
      window.removeEventListener("voice-message-recorded", listener as EventListener);
    };
  }, [handleVoiceMessage]);

  const handlePhotoUpload = useCallback(async (file: File) => {
    if (geoStatus !== "ready") return;
    setIsLoading(true);
    setMessages((prev) => [...prev, { role: "user", content: `📎 ${file.name}` }]);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("user_id", "web_citizen_1");
      formData.append("phone", "9876543210");
      formData.append("latitude", String(latitude));
      formData.append("longitude", String(longitude));

      const res = await sendChatRequest(CHAT_PHOTO_API, {
        method: "POST",
        body: formData,
      }, false);
      if (!res.ok) {
        if (res.status === 401) throw new Error("Session expired. Please login again.");
        const errText = await res.text();
        throw new Error(errText || `HTTP ${res.status}`);
      }

      const data = await res.json();
      const reply = typeof data.reply === "string" ? data.reply : String(data.reply ?? "");
      applyBotResponseMeta(data, reply);
      setMessages((prev) => [...prev, { role: "bot", content: reply }]);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "कुछ गलत हो गया। कृपया पुनः प्रयास करें।";
      setMessages((prev) => [...prev, { role: "bot", content: `त्रुटि (photo): ${errorMessage}` }]);
    } finally {
      setIsLoading(false);
    }
  }, [geoStatus, latitude, longitude, applyBotResponseMeta, sendChatRequest]);

  const handleNewChat = useCallback(() => {
    const ok = window.confirm(
      "Are you sure you want to clear this chat and start a new complaint?"
    );
    if (!ok) return;

    if (typeof window !== "undefined") {
      window.localStorage.removeItem(CHAT_DRAFT_STORAGE_KEY);
    }

    draftLoadedRef.current = false;
    setMessages([{ role: "bot", content: WELCOME_MESSAGE }]);
    setIsLoading(false);
    setExpectPhotoUpload(false);
    setShowLocationMap(false);
    setLocationConfirmed(false);
    setGeoError(null);
    setGeoStatus("pending");
    setLatitude(25.432);
    setLongitude(77.6644);
    requestLocation();
  }, [requestLocation]);

  if (!isReady || !isLoggedIn || geoStatus === "pending") {
    return (
      <div className="flex min-h-screen flex-col bg-slate-50">
        <header className="border-b border-emerald-700 bg-emerald-600 px-4 py-4 text-center text-white shadow">
          <h1 className="text-lg font-semibold">{APP_TITLE}</h1>
          <p className="mt-1 text-xs text-emerald-100">Pan-India civic assistant</p>
        </header>
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 py-8">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-md">
            <p className="text-sm text-slate-700">
              {!isReady || !isLoggedIn ? "Checking login session..." : "Getting your location…"}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              {!isReady || !isLoggedIn
                ? "Redirecting you to login if needed."
                : "We use your GPS so complaints route to the right city. Please allow location access when prompted."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (geoStatus === "unsupported" || geoStatus === "denied") {
    return (
      <div className="flex min-h-screen flex-col bg-slate-50">
        <header className="border-b border-emerald-700 bg-emerald-600 px-4 py-4 text-center text-white shadow">
          <h1 className="text-lg font-semibold">{APP_TITLE}</h1>
          <p className="mt-1 text-xs text-emerald-100">Location required</p>
        </header>
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 py-8">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-md">
            <h2 className="text-center text-base font-semibold text-slate-900">
              {geoStatus === "unsupported" ? "Location not available" : "Location permission needed"}
            </h2>
            <p className="mt-2 text-center text-sm text-slate-600 whitespace-pre-wrap">
              {geoError ?? "Enable location in your browser settings, then try again."}
            </p>
            <button
              type="button"
              onClick={() => requestLocation()}
              className="mt-6 w-full rounded-lg bg-emerald-600 py-3 text-sm font-semibold text-white hover:bg-emerald-700"
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen max-w-2xl mx-auto bg-gray-50">
      <ChatHeader subtitle={headerSubtitle} onNewChat={handleNewChat} />
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto py-2 min-h-0"
      >
        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}
        {isLoading && <TypingIndicator />}
      </div>
      {showLocationMap && (
        <div className="px-3 pb-2">
          <LocationMap
            latitude={latitude}
            longitude={longitude}
            onPositionChange={(lat, lng) => {
              setLatitude(lat);
              setLongitude(lng);
            }}
            onConfirm={(lat, lng) => {
              void confirmMapLocation(lat, lng);
            }}
          />
          <p className="mt-1 text-xs text-gray-600">
            Current location: {latitude.toFixed(6)}, {longitude.toFixed(6)}
            {locationConfirmed ? " (confirmed)" : ""}
          </p>
        </div>
      )}
      {!showLocationMap && locationConfirmed && (
        <p className="px-3 pb-2 text-xs text-gray-500">
          Pin: {latitude.toFixed(6)}, {longitude.toFixed(6)} (confirmed)
        </p>
      )}
      <ChatInput
        onSend={sendMessage}
        disabled={isLoading}
        photoUploadEnabled={expectPhotoUpload}
        onPhotoFile={handlePhotoUpload}
      />
    </div>
  );
}
