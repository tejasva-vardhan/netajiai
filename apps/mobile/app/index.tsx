import * as SecureStore from "expo-secure-store";
import * as Speech from "expo-speech";
import { Link } from "expo-router";
import { useEffect, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

const ONBOARDING_SEEN_KEY = "aineta.first_use_explainer_seen";

const EXPLAINER_STEPS = [
  { icon: "📷", title: "Photo aur jagah", detail: "Issue ki abhi photo aur GPS location li jayegi." },
  { icon: "🎙️", title: "Awaaz aur pushti", detail: "Aap apni baat bolenge. Bhejne se pehle AI Neta use suna kar poochega." },
  { icon: "🧾", title: "Receipt aur status", detail: "Receipt milegi. Isi se aap shikayat ka haal dekh sakte hain." },
];

const EXPLAINER_SPOKEN_TEXT = "AI Neta mein teen kadam hain. Pehle issue ki photo aur jagah li jayegi. Phir aap apni baat bolenge aur bhejne se pehle use suna kar aapse pushti li jayegi. Aakhir mein receipt milegi, jisse aap shikayat ka haal dekh sakte hain.";

export default function HomeScreen() {
  const [showExplainer, setShowExplainer] = useState(false);

  useEffect(() => {
    let active = true;
    void SecureStore.getItemAsync(ONBOARDING_SEEN_KEY).then((seen) => {
      if (active && !seen) setShowExplainer(true);
    });
    return () => {
      active = false;
      Speech.stop();
    };
  }, []);

  useEffect(() => {
    if (!showExplainer) return;
    Speech.stop();
    Speech.speak(EXPLAINER_SPOKEN_TEXT, { language: "hi-IN", rate: 0.88 });
  }, [showExplainer]);

  async function closeExplainer(): Promise<void> {
    Speech.stop();
    await SecureStore.setItemAsync(ONBOARDING_SEEN_KEY, "1");
    setShowExplainer(false);
  }

  function speakExplainer(): void {
    Speech.stop();
    Speech.speak(EXPLAINER_SPOKEN_TEXT, { language: "hi-IN", rate: 0.88 });
  }

  return (
    <>
      <View style={styles.container}>
        <Text style={styles.kicker}>AI NETA</Text>
        <Text style={styles.title}>Apne shehar ki baat batayein</Text>
        <Text style={styles.subtitle}>अपने शहर की बात बताएं</Text>
        <Text style={styles.help}>Photo, location aur chhoti voice note ke saath shikayat bhejein.</Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Pehli baar ke liye AI Neta kaise kaam karta hai sunayein" onPress={() => setShowExplainer(true)} style={styles.explainerLink}>
          <Text style={styles.explainerLinkText}>🔊  Pehli baar? Sun kar samjhein</Text>
        </Pressable>
        <Link href="/verify" style={styles.verify}>✅  Pehchaan verify karein</Link>
        <Link href="/chat" style={styles.chat}>💬  AI Neta se baat karein</Link>
        <Link href="/complaint" style={styles.primary}>📷  Shikayat darj karein</Link>
        <Link href="/track" style={styles.secondary}>🔎  Shikayat dekhein</Link>
        <Text style={styles.note}>Aapki receipt private rahegi. Public tracking mein sirf zaroori status dikhega.</Text>
      </View>
      <Modal visible={showExplainer} animationType="slide" onRequestClose={() => void closeExplainer()}>
        <ScrollView contentContainerStyle={styles.modalContainer}>
          <Text style={styles.modalKicker}>AI NETA</Text>
          <Text style={styles.modalTitle}>Yeh kaise kaam karta hai?</Text>
          <Text style={styles.modalHelp}>Aapko sirf teen chhote kadam lene hain.</Text>
          {EXPLAINER_STEPS.map((step, index) => (
            <View key={step.title} style={styles.stepCard}>
              <Text style={styles.stepNumber}>{index + 1}</Text>
              <Text style={styles.stepIcon} accessibilityLabel={step.title}>{step.icon}</Text>
              <View style={styles.stepCopy}>
                <Text style={styles.stepTitle}>{step.title}</Text>
                <Text style={styles.stepDetail}>{step.detail}</Text>
              </View>
            </View>
          ))}
          <Pressable accessibilityRole="button" onPress={speakExplainer} style={styles.listenButton}>
            <Text style={styles.listenButtonText}>🔊  Dobara sunayein</Text>
          </Pressable>
          <Pressable accessibilityRole="button" onPress={() => void closeExplainer()} style={styles.primary}>
            <Text style={styles.primaryText}>Samajh gaya</Text>
          </Pressable>
        </ScrollView>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 28, justifyContent: "center", backgroundColor: "#FFFDF7" },
  kicker: { color: "#0B6E4F", fontWeight: "800", letterSpacing: 2, fontSize: 14 },
  title: { marginTop: 18, fontSize: 36, lineHeight: 43, fontWeight: "800", color: "#17221D" },
  subtitle: { marginTop: 8, fontSize: 26, color: "#385449" },
  help: { marginTop: 24, fontSize: 20, lineHeight: 30, color: "#385449" },
  explainerLink: { marginTop: 22, padding: 10, alignSelf: "center" },
  explainerLinkText: { color: "#0B6E4F", fontSize: 17, fontWeight: "800" },
  primary: { marginTop: 34, backgroundColor: "#0B6E4F", color: "white", padding: 20, borderRadius: 16, textAlign: "center", fontSize: 20, fontWeight: "800" },
  verify: { marginTop: 26, color: "#0B6E4F", padding: 10, textAlign: "center", fontSize: 17, fontWeight: "800" },
  chat: { marginTop: 12, color: "#0B6E4F", padding: 10, textAlign: "center", fontSize: 17, fontWeight: "800" },
  secondary: { marginTop: 14, borderWidth: 2, borderColor: "#0B6E4F", color: "#0B6E4F", padding: 18, borderRadius: 16, textAlign: "center", fontSize: 19, fontWeight: "700" },
  note: { marginTop: 28, fontSize: 14, lineHeight: 21, color: "#5D6D65", textAlign: "center" },
  modalContainer: { flexGrow: 1, padding: 28, paddingTop: 76, paddingBottom: 40, backgroundColor: "#FFFDF7" },
  modalKicker: { color: "#0B6E4F", fontWeight: "800", letterSpacing: 2, fontSize: 14 },
  modalTitle: { marginTop: 18, fontSize: 32, lineHeight: 39, fontWeight: "800", color: "#17221D" },
  modalHelp: { marginTop: 14, fontSize: 19, lineHeight: 28, color: "#385449" },
  stepCard: { flexDirection: "row", alignItems: "center", marginTop: 18, padding: 16, borderRadius: 16, backgroundColor: "white", borderWidth: 1, borderColor: "#C9D8D0" },
  stepNumber: { width: 28, color: "#0B6E4F", fontSize: 18, fontWeight: "800" },
  stepIcon: { fontSize: 34, marginHorizontal: 10 },
  stepCopy: { flex: 1 },
  stepTitle: { color: "#17221D", fontSize: 18, fontWeight: "800" },
  stepDetail: { marginTop: 4, color: "#385449", fontSize: 16, lineHeight: 23 },
  listenButton: { marginTop: 26, padding: 17, borderRadius: 14, borderWidth: 2, borderColor: "#0B6E4F" },
  listenButtonText: { color: "#0B6E4F", textAlign: "center", fontSize: 17, fontWeight: "800" },
  primaryText: { color: "white", textAlign: "center", fontSize: 20, fontWeight: "800" },
});
