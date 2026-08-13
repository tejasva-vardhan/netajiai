import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";
import * as Speech from "expo-speech";
import { Link } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { getAccessToken, sendConversationTurn, ConversationSource, ConversationTurn } from "../src/api";

type ChatMessage = {
  id: string;
  author: "citizen" | "neta";
  text: string;
  response?: ConversationTurn;
};

const SESSION_KEY = "aineta.conversation_session_id";
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
  const [failedTurn, setFailedTurn] = useState<{
    text: string;
    idempotencyKey: string;
  } | null>(null);

  useEffect(() => {
    let active = true;
    void Promise.all([getAccessToken(), SecureStore.getItemAsync(SESSION_KEY)]).then(
      ([token, storedSessionId]) => {
        if (!active) return;
        setAuthenticated(Boolean(token));
        setSessionId(storedSessionId);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  async function send(messageText = text, retryKey?: string) {
    const trimmed = messageText.trim();
    if (!trimmed || busy) return;
    const idempotencyKey = retryKey ?? Crypto.randomUUID();
    const retrying = retryKey !== undefined;
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
      await SecureStore.setItemAsync(SESSION_KEY, response.session_id);
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
    } catch (sendError) {
      setFailedTurn({ text: trimmed, idempotencyKey });
      setError(sendError instanceof Error ? sendError.message : "Baat bheji nahi ja saki.");
    } finally {
      setBusy(false);
    }
  }

  async function resetConversation() {
    await SecureStore.deleteItemAsync(SESSION_KEY);
    setSessionId(null);
    setMessages([
      {
        id: "welcome-reset",
        author: "neta",
        text: "Nayi baat shuru karte hain. Main civic problem, status aur verified yojana ki jaankari mein madad kar sakta hoon.",
      },
    ]);
    setError("");
  }

  if (authenticated === null) {
    return <View style={styles.container}><Text style={styles.help}>Chat taiyaar ho rahi hai…</Text></View>;
  }
  if (!authenticated) {
    return (
      <View style={styles.container}>
        <Text style={styles.title}>Pehle sign-in karein</Text>
        <Text style={styles.help}>AI Neta chat aapki baat ko aapke account ke saath surakshit rakhti hai.</Text>
        <Link href="/verify" style={styles.primaryButton}>Sign-in / pehchaan verification</Link>
      </View>
    );
  }

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
            {message.response && <ActionHandoff response={message.response} />}
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
      {!!error && <Text style={styles.error} accessibilityLiveRegion="polite">Baat nahi pahunchi. Dobara try karein.</Text>}
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

function ActionHandoff({ response }: { response: ConversationTurn }) {
  if (response.next_action === "start_filing") {
    return <Link href="/complaint" style={styles.handoff}>Photo, location aur voice ke saath filing shuru karein →</Link>;
  }
  if (response.next_action === "verify_identity") {
    return <Link href="/verify" style={styles.handoff}>Pehchaan verification shuru karein →</Link>;
  }
  if (response.next_action === "provide_receipt") {
    return <Link href="/track" style={styles.handoff}>Receipt se status dekhein →</Link>;
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
  sources: { marginTop: 12, borderTopWidth: 1, borderTopColor: "#C9D8D0", paddingTop: 9 },
  sourceHeading: { color: "#385449", fontSize: 13, fontWeight: "800" },
  sourceText: { marginTop: 4, color: "#385449", fontSize: 13 },
  primaryButton: { marginTop: 28, backgroundColor: "#0B6E4F", color: "white", padding: 18, borderRadius: 14, textAlign: "center", fontSize: 17, fontWeight: "800" },
});
