import * as Speech from "expo-speech";
import { useEffect, useRef, useState } from "react";
import { StyleSheet, Text, TextInput, View, Pressable } from "react-native";
import {
  getAccessToken,
  getComplaint,
  getLastReceiptToken,
  getPublicComplaint,
  sendCitizenConfirmation,
  CitizenResolutionOutcome,
  ComplaintTracking,
  PublicComplaint,
} from "../src/api";

export default function TrackScreen() {
  const [token, setToken] = useState("");
  const [result, setResult] = useState<PublicComplaint | null>(null);
  const [privateResult, setPrivateResult] = useState<ComplaintTracking | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [lastReceiptAvailable, setLastReceiptAvailable] = useState(false);
  const [confirmationBusy, setConfirmationBusy] = useState(false);
  const [confirmationMessage, setConfirmationMessage] = useState("");
  const confirmationKeys = useRef(new Map<string, string>());

  useEffect(() => {
    let active = true;
    void getLastReceiptToken()
      .then((savedToken) => {
        if (active && savedToken) {
          setToken(savedToken);
          setLastReceiptAvailable(true);
        }
      })
      .catch(() => {
        // Manual token entry remains available when secure storage is locked
        // or unavailable on the current device.
      });
    return () => {
      active = false;
    };
  }, []);

  async function lookup(speakResult = false) {
    setLoading(true);
    setError("");
    setConfirmationMessage("");
    setResult(null);
    setPrivateResult(null);
    try {
      const publicResult = await getPublicComplaint(token.trim());
      setResult(publicResult);
      if (speakResult) speakStatus(publicResult.status);
      if (await getAccessToken()) {
        try {
          setPrivateResult(await getComplaint(publicResult.complaint_id));
        } catch {
          // A valid receipt may belong to another citizen; keep the redacted view.
        }
      }
    } catch {
      setError("Receipt nahi mili. Token dobara check karein.");
    } finally {
      setLoading(false);
    }
  }

  async function confirmResolution(outcome: CitizenResolutionOutcome): Promise<void> {
    if (!privateResult) return;
    const key = `${privateResult.complaint_id}:${outcome}`;
    const idempotencyKey = confirmationKeys.current.get(key) ?? `citizen-confirmation:${key}`;
    confirmationKeys.current.set(key, idempotencyKey);
    setConfirmationBusy(true);
    setError("");
    setConfirmationMessage("");
    try {
      await sendCitizenConfirmation(privateResult.complaint_id, outcome, idempotencyKey);
      await lookup();
      setConfirmationMessage(
        outcome === "fully_solved"
          ? "Aapki pushti mil gayi. Complaint band hone ka update thodi der mein dikhega."
          : outcome === "partially_solved"
            ? "Aapne bataya ki kaam kuchh hua hai. Baaki kaam ke liye follow-up jaari rahega."
            : "Aapki baat mil gayi. Complaint dobara follow-up mein ja rahi hai.",
      );
    } catch {
      setError("Pushti nahi pahunchi. Network check karke dobara try karein.");
    } finally {
      setConfirmationBusy(false);
    }
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Shikayat ka haal</Text>
      <Text style={styles.subtitle}>Receipt token daalein</Text>
      {lastReceiptAvailable && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Pichhli shikayat ka haal dekhein"
          onPress={() => void lookup(true)}
          disabled={loading}
          style={styles.lastReceiptButton}
        >
          <Text style={styles.lastReceiptButtonText}>
            🔊  Pichhli shikayat ka haal dekhein
          </Text>
        </Pressable>
      )}
      <TextInput value={token} onChangeText={setToken} autoCapitalize="none" placeholder="Receipt token" style={styles.input} />
      <Pressable onPress={() => void lookup()} disabled={loading || !token.trim()} style={styles.button}>
        <Text style={styles.buttonText}>{loading ? "Dekha ja raha hai…" : "Haal dekhein"}</Text>
      </Pressable>
      {!!error && <Text style={styles.error}>{error}</Text>}
      {result && (
        <View style={styles.card}>
          <StatusBadge status={result.status} />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Complaint ka status sunayein"
            onPress={() => speakStatus(result.status)}
            style={styles.speakButton}
          >
            <Text style={styles.speakText}>🔊 Status sunayein</Text>
          </Pressable>
          <Text>Issue: {result.issue_type ?? "Jaanch mein"}</Text>
          <Text>Zone: {result.execution_zone_state}</Text>
          <Text>Receipt ID: {result.complaint_id}</Text>
          {privateResult && (privateResult.status === "fix_reported" || privateResult.status === "awaiting_citizen_confirmation") && (
            <View style={styles.confirmation} accessibilityLiveRegion="polite">
              <Text style={styles.confirmationTitle}>Kaam kitna hua?</Text>
              <Text style={styles.confirmationHelp}>Aapki choice se AI Neta agla follow-up karega.</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Haan, kaam ho gaya"
                onPress={() => void confirmResolution("fully_solved")}
                disabled={confirmationBusy}
                style={styles.confirmButton}
              >
                <Text style={styles.confirmButtonText}>✅ Haan, kaam ho gaya</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Thoda kaam hua, follow-up chahiye"
                onPress={() => void confirmResolution("partially_solved")}
                disabled={confirmationBusy}
                style={styles.partialButton}
              >
                <Text style={styles.partialButtonText}>🟡 Thoda hua, baaki chahiye</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Nahi, kaam nahi hua"
                onPress={() => void confirmResolution("not_solved")}
                disabled={confirmationBusy}
                style={styles.reopenButton}
              >
                <Text style={styles.reopenButtonText}>❌ Nahi, kaam nahi hua</Text>
              </Pressable>
            </View>
          )}
          {!!confirmationMessage && <Text style={styles.confirmationMessage} accessibilityLiveRegion="polite">{confirmationMessage}</Text>}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Status dobara sunayein"
            onPress={() => speakStatus(result.status)}
            style={styles.repeatButton}
          >
            <Text style={styles.speakText}>🔁 Dobara sunayein</Text>
          </Pressable>
          {privateResult && privateResult.timeline.length > 0 && (
            <View style={styles.timeline}>
              <Text style={styles.timelineTitle}>Ab tak kya hua</Text>
              {privateResult.timeline.map((item, index) => (
                <View key={`${item.event_type}-${item.occurred_at}-${index}`} style={styles.timelineItem}>
                  <Text style={styles.timelineStatus}>{humanizeStatus(item.status)}</Text>
                  <Text style={styles.timelineDate}>{formatDate(item.occurred_at)}</Text>
                  {item.status === "escalated" && item.escalation_level !== null && (
                    <Text style={styles.timelineNote}>Level {item.escalation_level} par follow-up</Text>
                  )}
                </View>
              ))}
            </View>
          )}
        </View>
      )}
    </View>
  );
}

function StatusBadge({ status }: { status: string }) {
  const presentation = statusPresentation(status);
  return (
    <View style={[styles.statusBadge, { backgroundColor: presentation.backgroundColor }]}>
      <Text style={styles.statusIcon} accessibilityLabel={presentation.label}>{presentation.icon}</Text>
      <View>
        <Text style={styles.statusLabel}>Aapki shikayat</Text>
        <Text style={[styles.cardTitle, { color: presentation.color }]}>{presentation.label}</Text>
      </View>
    </View>
  );
}

function statusPresentation(status: string): { label: string; icon: string; color: string; backgroundColor: string } {
  if (status === "closed") return { label: "Kaam poora bataya gaya", icon: "✅", color: "#176B4B", backgroundColor: "#D8EEE4" };
  if (status === "escalated" || status === "not_accepted") return { label: "Follow-up zaroori hai", icon: "⚠️", color: "#9B2C2C", backgroundColor: "#FBE3E3" };
  if (status === "fix_reported" || status === "awaiting_citizen_confirmation") return { label: "Aapki pushti zaroori hai", icon: "🙋", color: "#245B8A", backgroundColor: "#E0EEF8" };
  if (status === "sent" || status === "awaiting_response") return { label: "Department ke jawaab ka intezar", icon: "⏳", color: "#8A5A00", backgroundColor: "#FFF1C7" };
  return { label: "Jaanch aur mapping chal rahi hai", icon: "🔎", color: "#385449", backgroundColor: "#E7F3ED" };
}

function speakStatus(status: string): void {
  Speech.stop();
  Speech.speak(`Aapki shikayat ka status: ${statusPresentation(status).label}`, {
    language: "hi-IN",
    rate: 0.88,
  });
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 28, paddingTop: 80, backgroundColor: "#FFFDF7" },
  title: { fontSize: 32, fontWeight: "800", color: "#17221D" },
  subtitle: { marginTop: 8, fontSize: 19, color: "#385449" },
  input: { marginTop: 24, borderWidth: 1, borderColor: "#B6C5BE", borderRadius: 12, padding: 16, fontSize: 18, backgroundColor: "white" },
  lastReceiptButton: { marginTop: 22, padding: 18, borderRadius: 14, backgroundColor: "#E7F3ED", borderWidth: 2, borderColor: "#0B6E4F" },
  lastReceiptButtonText: { color: "#0B6E4F", textAlign: "center", fontWeight: "800", fontSize: 17 },
  button: { marginTop: 16, padding: 18, borderRadius: 14, backgroundColor: "#0B6E4F" },
  buttonText: { color: "white", textAlign: "center", fontWeight: "800", fontSize: 18 },
  error: { marginTop: 18, color: "#A52A2A", fontSize: 16 },
  card: { marginTop: 24, padding: 20, borderRadius: 16, backgroundColor: "#E7F3ED", gap: 10 },
  statusBadge: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, borderRadius: 12 },
  statusIcon: { fontSize: 28 },
  statusLabel: { color: "#5D6D65", fontSize: 12, fontWeight: "700" },
  cardTitle: { fontSize: 21, fontWeight: "800", color: "#0B6E4F" },
  speakButton: { alignSelf: "flex-start", paddingVertical: 4 },
  repeatButton: { alignSelf: "flex-start", paddingVertical: 4 },
  speakText: { color: "#0B6E4F", fontSize: 15, fontWeight: "800" },
  timeline: { marginTop: 14, paddingTop: 14, borderTopWidth: 1, borderTopColor: "#B6C5BE", gap: 12 },
  timelineTitle: { fontSize: 18, fontWeight: "800", color: "#17221D" },
  timelineItem: { paddingLeft: 12, borderLeftWidth: 3, borderLeftColor: "#0B6E4F" },
  timelineStatus: { fontSize: 16, fontWeight: "700", color: "#17221D" },
  timelineDate: { marginTop: 3, fontSize: 13, color: "#5D6D65" },
  timelineNote: { marginTop: 3, fontSize: 14, color: "#385449" },
  confirmation: { marginTop: 8, padding: 14, borderRadius: 12, backgroundColor: "#FFF1C7", gap: 10 },
  confirmationTitle: { fontSize: 18, fontWeight: "800", color: "#17221D" },
  confirmationHelp: { fontSize: 15, color: "#385449" },
  confirmButton: { padding: 15, borderRadius: 12, backgroundColor: "#176B4B" },
  confirmButtonText: { color: "white", textAlign: "center", fontSize: 16, fontWeight: "800" },
  reopenButton: { padding: 15, borderRadius: 12, borderWidth: 2, borderColor: "#9B2C2C", backgroundColor: "white" },
  reopenButtonText: { color: "#9B2C2C", textAlign: "center", fontSize: 16, fontWeight: "800" },
  partialButton: { padding: 15, borderRadius: 12, borderWidth: 2, borderColor: "#8A5A00", backgroundColor: "white" },
  partialButtonText: { color: "#8A5A00", textAlign: "center", fontSize: 16, fontWeight: "800" },
  confirmationMessage: { marginTop: 12, color: "#176B4B", fontSize: 16, fontWeight: "700" },
});

function humanizeStatus(status: string): string {
  return status.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Update available" : new Intl.DateTimeFormat("hi-IN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
