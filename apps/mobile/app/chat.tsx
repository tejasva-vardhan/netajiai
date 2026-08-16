import * as Crypto from "expo-crypto";
import * as Speech from "expo-speech";
import { Link, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { getAccessToken, getIdentityVerificationStatus, getPublicComplaint, sendConversationTurn, ConversationSource, ConversationTurn, PublicComplaint } from "../src/api";
import { CONVERSATION_SESSION_KEY, parsePendingFilingDraft, PENDING_FILING_DRAFT_KEY } from "../src/conversation";
import { deleteStoredValue, getStoredValue, setStoredValue } from "../src/storage";

type ChatMessage = {
  id: string;
  author: "citizen" | "neta";
  text: string;
  response?: ConversationTurn;
};

const QUICK_PROMPTS = [
  "Meri civic shikayat darj karni hai",
  "Meri shikayat ka status dekhna hai",
  "Sarkari yojana ke baare mein batao",
];

export default function ChatScreen() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      author: "neta",
      text: "Namaste! Main AI Neta hoon. Civic problem batayein, status poochhein, ya verified yojana ki jaankari maangein.",
    },
  ]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [authLoadError, setAuthLoadError] = useState("");
  const [receiptToken, setReceiptToken] = useState("");
  const [receiptStatus, setReceiptStatus] = useState<PublicComplaint | null>(null);
  const [receiptStatusBusy, setReceiptStatusBusy] = useState(false);
  const [receiptStatusError, setReceiptStatusError] = useState("");
  const [failedTurn, setFailedTurn] = useState<{
    text: string;
    idempotencyKey: string;
  } | null>(null);
  const verificationResumeInFlightRef = useRef(false);
  const verificationResumeTextRef = useRef<string | null>(null);
  const verificationResumeIdempotencyKeyRef = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    void Promise.allSettled([getAccessToken(), getStoredValue(CONVERSATION_SESSION_KEY)]).then(
      ([tokenResult, sessionResult]) => {
        if (!active) return;
        const token = tokenResult.status === "fulfilled" ? tokenResult.value : null;
        const storedSessionId = sessionResult.status === "fulfilled" ? sessionResult.value : null;
        setAuthenticated(Boolean(token));
        setSessionId(storedSessionId || null);
        if (tokenResult.status === "rejected") {
          setAuthLoadError("Secure sign-in session nahi padh pa rahe. Dobara sign-in karein.");
        } else if (sessionResult.status === "rejected") {
          setError("Sign-in ho gaya. Conversation session is app visit ke liye hi rahega.");
        }
      },
    );
    return () => {
      active = false;
    };
  }, []);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      const latestResponse = messages[messages.length - 1]?.response;
      if (!latestResponse || latestResponse.next_action !== "verify_identity" || verificationResumeInFlightRef.current) {
        return () => {
          active = false;
        };
      }
      verificationResumeInFlightRef.current = true;

      void getIdentityVerificationStatus()
        .then(async (status) => {
          if (!active || status.status !== "verified") return;
          let handoffText = "haan";
          try {
            const handoff = parsePendingFilingDraft(await getStoredValue(PENDING_FILING_DRAFT_KEY));
            if (handoff?.description.trim()) handoffText = handoff.description.trim();
          } catch {
            // The bounded continuation below can still resume the workflow.
          }
          if (verificationResumeTextRef.current === handoffText && verificationResumeIdempotencyKeyRef.current) return;
          const idempotencyKey = verificationResumeIdempotencyKeyRef.current ?? Crypto.randomUUID();
          verificationResumeTextRef.current = handoffText;
          verificationResumeIdempotencyKeyRef.current = idempotencyKey;
          setBusy(true);
          setError("");
          try {
            const response = await sendConversationTurn({
              text: handoffText,
              language: "hi-IN",
              sessionId,
              idempotencyKey,
            });
            if (!active) {
              // The route may have blurred while the request was in flight.
              // Keep the idempotency key for a safe replay, but let the next
              // focus attempt the handoff again.
              verificationResumeTextRef.current = null;
              return;
            }
            setSessionId(response.session_id);
            try {
              await setStoredValue(CONVERSATION_SESSION_KEY, response.session_id);
            } catch {
              setError("Verification ho gayi. Conversation session device par save nahi ho saka.");
            }
            setMessages((current) => [
              ...current,
              { id: response.response_id, author: "neta", text: response.response_text, response },
            ]);
            speak(response.response_text);
          } catch (resumeError) {
            if (!active) {
              verificationResumeTextRef.current = null;
              return;
            }
            if (active) {
              setFailedTurn({ text: handoffText, idempotencyKey });
              setError(resumeError instanceof Error ? resumeError.message : "Complaint dobara shuru nahi ho saki.");
            }
          }
        })
        .catch((statusError) => {
          if (active && statusError instanceof Error) setError(statusError.message);
        })
        .finally(() => {
          verificationResumeInFlightRef.current = false;
          setBusy(false);
        });

    return () => {
        active = false;
      };
    }, [messages, sessionId]),
  );

  async function send(messageText = text, retryKey?: string) {
    const trimmed = messageText.trim();
    if (!trimmed || busy) return;
    const retrying = retryKey !== undefined;
    if (!retrying) {
      verificationResumeTextRef.current = null;
      verificationResumeIdempotencyKeyRef.current = null;
    }
    const idempotencyKey = retryKey ?? Crypto.randomUUID();
    setText("");
    setError("");
    setFailedTurn(null);
    setBusy(true);
    if (!retrying) {
      setMessages((current) => [
        ...current,
        { id: `citizen-${Crypto.randomUUID()}`, author: "citizen", text: trimmed },
      ]);
    }
    try {
      const response = await sendConversationTurn({
        text: trimmed,
        language: "hi-IN",
        sessionId,
        idempotencyKey,
      });
      setSessionId(response.session_id);
      let localStorageWarning = false;
      try {
        await setStoredValue(CONVERSATION_SESSION_KEY, response.session_id);
      } catch {
        localStorageWarning = true;
      }
      if (response.intent === "filing") {
        try {
          const previousDraft = parsePendingFilingDraft(await getStoredValue(PENDING_FILING_DRAFT_KEY));
          const previousDescription = previousDraft?.description.trim() ?? "";
          const nextDescription = !previousDescription || previousDescription.toLocaleLowerCase().includes(trimmed.toLocaleLowerCase())
            ? previousDescription || trimmed
            : `${previousDescription}\n${trimmed}`;
          await setStoredValue(
            PENDING_FILING_DRAFT_KEY,
            JSON.stringify({
              description: nextDescription,
              issueType: response.complaint_draft?.issue_type ?? previousDraft?.issueType ?? null,
              language: "hi-IN",
              expiresAt: Date.now() + 30 * 60_000,
            }),
          );
        } catch {
          localStorageWarning = true;
        }
      }
      setMessages((current) => [
        ...current,
        {
          id: response.response_id,
          author: "neta",
          text: response.response_text,
          response,
        },
      ]);
      speak(response.response_text);
      if (localStorageWarning) {
        setError("Baat ho gayi. Device par session save nahi ho saka; app band na karein, warna yeh handoff dobara dikhani pad sakti hai.");
      }
    } catch (sendError) {
      setFailedTurn({ text: trimmed, idempotencyKey });
      setError(sendError instanceof Error ? sendError.message : "Baat bheji nahi ja saki.");
    } finally {
      setBusy(false);
    }
  }

  async function resetConversation() {
    const cleanup = await Promise.allSettled([
      deleteStoredValue(CONVERSATION_SESSION_KEY),
      deleteStoredValue(PENDING_FILING_DRAFT_KEY),
    ]);
    setSessionId(null);
    setReceiptToken("");
    setReceiptStatus(null);
    setReceiptStatusError("");
    verificationResumeTextRef.current = null;
    verificationResumeIdempotencyKeyRef.current = null;
    setMessages([
      {
        id: "welcome-reset",
        author: "neta",
        text: "Nayi baat shuru karte hain. Main civic problem, status aur verified yojana ki jaankari mein madad kar sakta hoon.",
      },
    ]);
    setError(cleanup.some((result) => result.status === "rejected")
      ? "Nayi baat shuru ho gayi. Purani device copy poori tarah delete nahi ho saki."
      : "");
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
    } catch (lookupError) {
      setReceiptStatusError(lookupError instanceof Error ? lookupError.message : "Status nahi mil saka.");
    } finally {
      setReceiptStatusBusy(false);
    }
  }

  if (authenticated === null) {
    return <View style={styles.container}><Text style={styles.help}>Chat taiyaar ho rahi hai…</Text></View>;
  }
  if (!authenticated) {
    return (
      <View style={styles.container}>
        <Text style={styles.title}>Pehle sign-in karein</Text>
        <Text style={styles.help}>AI Neta chat aapki baat ko aapke account ke saath surakshit rakhti hai.</Text>
        {!!authLoadError && <Text style={styles.error} accessibilityLiveRegion="polite">{authLoadError}</Text>}
        <Link href="/verify" style={styles.primaryButton}>Sign-in / pehchaan verification</Link>
      </View>
    );
  }

  const latestMessage = messages[messages.length - 1];
  const latestResponseId = latestMessage?.response ? latestMessage.id : null;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <View>
          <Text style={styles.kicker}>AI NETA</Text>
          <Text style={styles.title}>Baat kijiye</Text>
        </View>
        <Pressable accessibilityRole="button" onPress={() => void resetConversation()}>
          <Text style={styles.reset}>Nayi baat</Text>
        </Pressable>
      </View>
      <ScrollView style={styles.messages} contentContainerStyle={styles.messageContent} keyboardShouldPersistTaps="handled">
        {messages.map((message) => (
          <View key={message.id} style={[styles.message, message.author === "citizen" ? styles.citizenMessage : styles.netaMessage]}>
            <Text style={styles.messageAuthor}>{message.author === "citizen" ? "Aap" : "AI Neta"}</Text>
            <Text style={styles.messageText}>{message.text}</Text>
            {message.author === "neta" && (
              <Pressable accessibilityRole="button" onPress={() => speak(message.text)} style={styles.speakButton}>
                <Text style={styles.speakText}>🔊 Sunayein</Text>
              </Pressable>
            )}
            {message.response && message.id === latestResponseId && <ActionHandoff response={message.response} receiptToken={receiptToken} receiptStatus={receiptStatus} receiptStatusBusy={receiptStatusBusy} receiptStatusError={receiptStatusError} onReceiptTokenChange={setReceiptToken} onLookupReceipt={() => void lookupReceiptStatus()} />}
          </View>
        ))}
        {busy && <Text style={styles.typing}>AI Neta soch raha hai…</Text>}
      </ScrollView>
      <View style={styles.quickPrompts}>
        {QUICK_PROMPTS.map((prompt) => (
          <Pressable key={prompt} disabled={busy} onPress={() => void send(prompt)} style={styles.prompt}>
            <Text style={styles.promptText}>{prompt}</Text>
          </Pressable>
        ))}
      </View>
      <View style={styles.composer}>
        <TextInput
          value={text}
          onChangeText={setText}
          onSubmitEditing={() => void send()}
          editable={!busy}
          placeholder="Apni baat yahan likhein…"
          accessibilityLabel="Apni baat likhein"
          style={styles.input}
          returnKeyType="send"
        />
        <Pressable accessibilityRole="button" disabled={busy || !text.trim()} onPress={() => void send()} style={styles.sendButton}>
          <Text style={styles.sendText}>Bhejein</Text>
        </Pressable>
      </View>
      {!!error && <Text style={styles.error} accessibilityLiveRegion="polite">{error}</Text>}
      {error && failedTurn && error.includes("session expire") && <Link href="/verify" style={styles.handoff}>Sign-in dobara karein →</Link>}
      {failedTurn && (
        <Pressable
          accessibilityRole="button"
          disabled={busy}
          onPress={() => void send(failedTurn.text, failedTurn.idempotencyKey)}
          style={styles.retryButton}
        >
          <Text style={styles.retryText}>Dobara bhejein</Text>
        </Pressable>
      )}
    </View>
  );
}

function speak(text: string): void {
  Speech.stop();
  Speech.speak(text, { language: "hi-IN", rate: 0.88 });
}

function ActionHandoff({
  response,
  receiptToken,
  receiptStatus,
  receiptStatusBusy,
  receiptStatusError,
  onReceiptTokenChange,
  onLookupReceipt,
}: {
  response: ConversationTurn;
  receiptToken: string;
  receiptStatus: PublicComplaint | null;
  receiptStatusBusy: boolean;
  receiptStatusError: string;
  onReceiptTokenChange: (value: string) => void;
  onLookupReceipt: () => void;
}) {
  if (response.next_action === "start_filing") {
    return <Link href="/complaint" style={styles.handoff}>Photo, location aur voice ke saath filing shuru karein →</Link>;
  }
  if (response.next_action === "verify_identity") {
    return <Link href="/verify" style={styles.handoff}>Pehchaan verification shuru karein →</Link>;
  }
  if (response.next_action === "provide_receipt") {
    return (
      <View style={styles.handoffCard}>
        <Text style={styles.handoffLabel}>Receipt token se status dekhein</Text>
        <TextInput
          value={receiptToken}
          onChangeText={onReceiptTokenChange}
          placeholder="Receipt token yahan likhein"
          autoCapitalize="none"
          autoCorrect={false}
          style={styles.handoffInput}
        />
        <Pressable accessibilityRole="button" disabled={receiptStatusBusy} onPress={onLookupReceipt} style={styles.handoffButton}>
          <Text style={styles.handoffButtonText}>{receiptStatusBusy ? "Dekh rahe hain…" : "Status dekhein"}</Text>
        </Pressable>
        {!!receiptStatusError && <Text style={styles.handoffError}>{receiptStatusError}</Text>}
        {receiptStatus && <View style={styles.handoffResult}><Text style={styles.handoffResultStatus}>{receiptStatus.status.replace(/_/g, " ")}</Text><Text style={styles.handoffResultText}>{receiptStatus.issue_type ?? "Civic issue"} · {receiptStatus.execution_zone_state.replace(/_/g, " ")}</Text></View>}
      </View>
    );
  }
  if (response.scheme_sources.length > 0) {
    return <View style={styles.sources}><Text style={styles.sourceHeading}>Verified source</Text>{response.scheme_sources.map((source) => <SourceLine key={source.source_id} source={source} />)}</View>;
  }
  return null;
}

function SourceLine({ source }: { source: ConversationSource }) {
  return <Text style={styles.sourceText}>{source.title}</Text>;
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20, paddingTop: 64, backgroundColor: "#FFFDF7" },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  kicker: { color: "#0B6E4F", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
  title: { marginTop: 6, fontSize: 30, lineHeight: 37, fontWeight: "800", color: "#17221D" },
  help: { marginTop: 20, fontSize: 19, lineHeight: 29, color: "#385449" },
  reset: { color: "#0B6E4F", fontWeight: "800", padding: 8 },
  messages: { flex: 1, marginTop: 18 },
  messageContent: { gap: 12, paddingBottom: 12 },
  message: { maxWidth: "92%", padding: 15, borderRadius: 16 },
  citizenMessage: { alignSelf: "flex-end", backgroundColor: "#D8EEE4" },
  netaMessage: { alignSelf: "flex-start", backgroundColor: "white", borderWidth: 1, borderColor: "#C9D8D0" },
  messageAuthor: { color: "#385449", fontSize: 12, fontWeight: "800", marginBottom: 5 },
  messageText: { color: "#17221D", fontSize: 17, lineHeight: 25 },
  speakButton: { marginTop: 10, alignSelf: "flex-start" },
  speakText: { color: "#0B6E4F", fontSize: 14, fontWeight: "800" },
  typing: { color: "#5D6D65", fontSize: 14, padding: 8 },
  quickPrompts: { gap: 8, paddingVertical: 8 },
  prompt: { borderWidth: 1, borderColor: "#9FBAAC", borderRadius: 18, paddingVertical: 9, paddingHorizontal: 12, alignSelf: "flex-start" },
  promptText: { color: "#0B6E4F", fontSize: 14, fontWeight: "700" },
  composer: { flexDirection: "row", gap: 8, alignItems: "flex-end" },
  input: { flex: 1, minHeight: 50, maxHeight: 110, borderWidth: 1, borderColor: "#B6C5BE", borderRadius: 13, padding: 13, fontSize: 17, backgroundColor: "white" },
  sendButton: { minHeight: 50, paddingHorizontal: 14, borderRadius: 13, backgroundColor: "#0B6E4F", justifyContent: "center" },
  sendText: { color: "white", fontWeight: "800" },
  error: { marginTop: 8, color: "#A52A2A", fontSize: 14 },
  retryButton: { marginTop: 8, padding: 10, alignSelf: "flex-start" },
  retryText: { color: "#0B6E4F", fontSize: 15, fontWeight: "800" },
  handoff: { marginTop: 12, color: "#0B6E4F", fontSize: 15, fontWeight: "800" },
  handoffCard: { marginTop: 12, padding: 12, borderRadius: 12, backgroundColor: "#F1F8F4" },
  handoffLabel: { color: "#385449", fontSize: 14, fontWeight: "800" },
  handoffInput: { marginTop: 9, borderWidth: 1, borderColor: "#B6C5BE", borderRadius: 10, padding: 11, fontSize: 15, backgroundColor: "white" },
  handoffButton: { marginTop: 9, padding: 12, borderRadius: 10, backgroundColor: "#0B6E4F" },
  handoffButtonText: { color: "white", textAlign: "center", fontWeight: "800" },
  handoffError: { marginTop: 8, color: "#A52A2A", fontSize: 13 },
  handoffResult: { marginTop: 10, paddingTop: 9, borderTopWidth: 1, borderTopColor: "#C9D8D0" },
  handoffResultStatus: { color: "#0B6E4F", fontSize: 16, fontWeight: "800", textTransform: "capitalize" },
  handoffResultText: { marginTop: 3, color: "#385449", fontSize: 13 },
  sources: { marginTop: 12, borderTopWidth: 1, borderTopColor: "#C9D8D0", paddingTop: 9 },
  sourceHeading: { color: "#385449", fontSize: 13, fontWeight: "800" },
  sourceText: { marginTop: 4, color: "#385449", fontSize: 13 },
  primaryButton: { marginTop: 28, backgroundColor: "#0B6E4F", color: "white", padding: 18, borderRadius: 14, textAlign: "center", fontSize: 17, fontWeight: "800" },
});
