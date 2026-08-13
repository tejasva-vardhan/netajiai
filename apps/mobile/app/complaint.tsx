import { CameraView, useCameraPermissions } from "expo-camera";
import * as Crypto from "expo-crypto";
import * as Location from "expo-location";
import * as Speech from "expo-speech";
import { AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder, useAudioRecorderState } from "expo-audio";
import { File } from "expo-file-system";
import * as SecureStore from "expo-secure-store";
import { Link } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import {
  ComplaintCategory,
  createComplaintDraft,
  ComplaintDraft,
  getAccessToken,
  getAuthSessionId,
  getComplaintCategories,
  getIdentityVerificationStatus,
  recordDisclosureConsent,
  saveLastReceiptToken,
} from "../src/api";
import { queueCapture, removeQueuedCapture, Capture, QueuedCapture } from "../src/queue";
import {
  createVoiceDraftForCapture,
  EvidenceRejectedError,
  EvidenceReviewPendingError,
  submitCapturedComplaint,
} from "../src/submission";

type Stage = "photo" | "category" | "voice" | "confirm" | "sending" | "disclosure" | "receipt";

const CATEGORY_CACHE_KEY = "aineta.complaint_category_catalog";

export default function ComplaintScreen() {
  const cameraRef = useRef<CameraView>(null);
  const submissionId = useRef(Crypto.randomUUID());
  const [permission, requestPermission] = useCameraPermissions();
  const [stage, setStage] = useState<Stage>("photo");
  const [categories, setCategories] = useState<ComplaintCategory[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<ComplaintCategory | null>(null);
  const [photoUri, setPhotoUri] = useState<string | null>(null);
  const [audioUri, setAudioUri] = useState<string | null>(null);
  const [location, setLocation] = useState<Location.LocationObject | null>(null);
  const [description, setDescription] = useState("");
  const [draft, setDraft] = useState<ComplaintDraft | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [complaintId, setComplaintId] = useState<string | null>(null);
  const [disclosureBusy, setDisclosureBusy] = useState(false);
  const [error, setError] = useState("");
  const [verificationReady, setVerificationReady] = useState<boolean | null>(null);
  const recorder = useAudioRecorder(RecordingPresets.LOW_QUALITY);
  const recorderState = useAudioRecorderState(recorder);

  useEffect(() => {
    let active = true;
    void getAccessToken()
      .then(async (token) => {
        if (!token) return false;
        const status = await getIdentityVerificationStatus();
        return status.status === "verified";
      })
      .then((ready) => {
        if (active) setVerificationReady(ready);
      })
      .catch(() => {
        if (active) setVerificationReady(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (stage !== "disclosure") return;
    Speech.stop();
    Speech.speak(
      "Aapki pehchaan private rahe? Complaint verify ho gayi hai. Aapka naam public nahi dikhaya jayega.",
      { language: "hi-IN", rate: 0.88 },
    );
  }, [stage]);

  useEffect(() => {
    let active = true;
    void getComplaintCategories()
      .then(async (catalog) => {
        await SecureStore.setItemAsync(CATEGORY_CACHE_KEY, JSON.stringify(catalog));
        if (active) setCategories(catalog.items);
      })
      .catch(async () => {
        const cached = await SecureStore.getItemAsync(CATEGORY_CACHE_KEY);
        if (!cached || !active) return;
        try {
          const catalog = JSON.parse(cached) as { items?: ComplaintCategory[] };
          if (Array.isArray(catalog.items)) setCategories(catalog.items);
        } catch {
          // Ignore a corrupt cache; the online catalogue will be retried next launch.
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function capturePhoto() {
    setError("");
    const services = await Location.hasServicesEnabledAsync();
    if (!services) return setError("Location on karke phir photo lein.");
    const locationPermission = await Location.requestForegroundPermissionsAsync();
    if (locationPermission.status !== "granted") return setError("Location permission zaroori hai.");
    const nextLocation = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
    const photo = await cameraRef.current?.takePictureAsync({ quality: 0.7 });
    if (!photo?.uri) return setError("Photo nahi li ja saki. Dobara try karein.");
    setPhotoUri(photo.uri);
    setLocation(nextLocation);
    setStage("category");
  }

  function chooseCategory(category: ComplaintCategory): void {
    setSelectedCategory(category);
    Speech.stop();
    Speech.speak(category.spoken_hi, { language: "hi-IN", rate: 0.88 });
    setStage("voice");
  }

  async function startVoice() {
    setError("");
    const permissionStatus = await AudioModule.requestRecordingPermissionsAsync();
    if (!permissionStatus.granted) return setError("Voice note ke liye microphone permission zaroori hai.");
    await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    await recorder.prepareToRecordAsync();
    recorder.record();
  }

  async function stopVoice() {
    await recorder.stop();
    if (!recorder.uri) return setError("Voice note nahi mili. Dobara record karein.");
    setAudioUri(recorder.uri);
    setStage("confirm");
  }

  function readBackText(currentDraft: ComplaintDraft): string {
    const issue = currentDraft.issue_type ?? "is civic issue";
    const details = currentDraft.description ?? description.trim();
    return `Yeh shikayat ${issue} ke baare mein hai. ${details}. Kya yeh sahi hai?`;
  }

  function speakDraft(currentDraft: ComplaintDraft): void {
    Speech.stop();
    Speech.speak(readBackText(currentDraft), {
      language: currentDraft.language || "hi-IN",
      rate: 0.88,
    });
  }

  async function reviewOrSubmit() {
    if (!draft || !draft.issue_type || !draft.description || draft.missing_fields.length > 0) {
      setError("");
      setDraftLoading(true);
      try {
        if (!photoUri || !audioUri || !location) {
          setError("Photo, voice note aur location zaroori hai.");
          return;
        }
        const captureForDraft: Capture = {
          id: submissionId.current,
          photoUri,
          audioUri,
          latitude: location.coords.latitude,
          longitude: location.coords.longitude,
          accuracyM: Math.max(location.coords.accuracy ?? 1, 1),
          issueType: selectedCategory?.code ?? "voice_pending",
          description: "",
          language: "hi-IN",
        };
        const extractedDraft = description.trim()
          ? await createComplaintDraft({ text: description.trim(), language: "hi-IN" })
          : await createVoiceDraftForCapture(captureForDraft);
        const nextDraft = selectedCategory
          ? {
              ...extractedDraft,
              issue_type: selectedCategory.code,
              missing_fields: extractedDraft.missing_fields.filter((field) => field !== "issue_type"),
            }
          : extractedDraft;
        setDraft(nextDraft);
        if (nextDraft.missing_fields.length > 0 || !nextDraft.issue_type) {
          setError("Baat poori samajh nahi aayi. Issue ka naam bhi batayein, jaise sadak, paani ya light.");
          return;
        }
        speakDraft(nextDraft);
      } catch (draftError) {
        if (draftError instanceof EvidenceReviewPendingError) {
          setError(
            "Voice ki jaanch chal rahi hai. Thodi der baad isi screen par dobara koshish karein.",
          );
        } else if (draftError instanceof EvidenceRejectedError) {
          setError("Voice note accept nahi hui. Nayi voice note record karein.");
        } else {
          setError(
            draftError instanceof Error
              ? draftError.message
              : "Baat samajhne mein dikkat hui. Dobara try karein.",
          );
        }
      } finally {
        setDraftLoading(false);
      }
      return;
    }
    await submit(draft);
  }

  async function submit(currentDraft: ComplaintDraft) {
    if (!photoUri || !audioUri || !location || !currentDraft.issue_type || !currentDraft.description) {
      return setError("Photo, voice note aur samjhi hui shikayat zaroori hai.");
    }
    setError("");
    let authSessionId: string | null = null;
    try {
      authSessionId = await getAuthSessionId();
    } catch {
      setError("Sign-in session nahi mil raha. Dobara sign-in karein.");
      return;
    }
    if (!authSessionId) {
      setError("Sign-in session nahi mil raha. Dobara sign-in karein.");
      return;
    }
    setStage("sending");
    const capture: QueuedCapture = {
      id: submissionId.current,
      photoUri,
      audioUri,
      latitude: location.coords.latitude,
      longitude: location.coords.longitude,
      accuracyM: Math.max(location.coords.accuracy ?? 1, 1),
      issueType: currentDraft.issue_type,
      description: currentDraft.description,
      language: currentDraft.language,
      authSessionId,
    };
    try {
      const result = await submitCapturedComplaint(capture);
      await removeQueuedCapture(capture.id);
      try {
        await saveLastReceiptToken(result.tracking_token);
      } catch {
        // Secure-store persistence improves the next visit but must not turn a
        // server-confirmed complaint into a false submission failure.
      }
      setComplaintId(result.complaint_id);
      setReceipt(result.tracking_token);
      setStage("disclosure");
    } catch (submissionError) {
      let queued = true;
      try {
        if (!(submissionError instanceof EvidenceRejectedError)) {
          await queueCapture(capture);
        } else {
          queued = false;
        }
      } catch {
        queued = false;
      }
      setStage("confirm");
      if (submissionError instanceof EvidenceReviewPendingError) {
        setError(
          "Photo ya voice ki jaanch chal rahi hai. App khula rakhein ya baad mein dobara kholein; jaanch poori hone par shikayat bheji jayegi.",
        );
        return;
      }
      const savedMessage = queued
        ? "Data phone mein surakshit rakha gaya hai."
        : "Data phone mein save nahi ho saka. Is screen ko band na karein.";
      setError(
        submissionError instanceof Error
          ? `${submissionError.message}. ${savedMessage}`
          : `Network nahi mila. ${savedMessage}`,
      );
    }
  }

  async function keepDisclosurePrivate(): Promise<void> {
    if (!complaintId) return;
    setDisclosureBusy(true);
    setError("");
    try {
      await recordDisclosureConsent(
        complaintId,
        "verified_citizen",
        `capture:${submissionId.current}:disclosure-private`,
      );
      setStage("receipt");
    } catch {
      setError("Complaint bhej di gayi hai, privacy choice save nahi hui. Dobara try karein.");
    } finally {
      setDisclosureBusy(false);
    }
  }

  if (stage === "receipt") {
    return <View style={styles.container}><Text style={styles.title}>Shikayat bhej di gayi ✅</Text><Text style={styles.help}>Is receipt token ko sambhal kar rakhein:</Text><Text selectable style={styles.receipt}>{receipt}</Text><Text style={styles.note}>Isi token se shikayat ka haal dekha ja sakta hai.</Text><Link href="/track" style={styles.button}>🔊  Abhi status dekhein</Link></View>;
  }
  if (stage === "disclosure") {
    return <View style={styles.container}>
      <Text style={styles.title}>Aapki pehchaan private rahe?</Text>
      <Text style={styles.help}>Complaint verify ho gayi hai. Aapka naam public nahi dikhaya jayega.</Text>
      <Pressable accessibilityRole="button" accessibilityLabel="Haan, complaint private rakhein" style={styles.button} onPress={() => void keepDisclosurePrivate()} disabled={disclosureBusy}>
        <Text style={styles.buttonText}>{disclosureBusy ? "Save ho raha hai…" : "🔒 Haan, private rakhein"}</Text>
      </Pressable>
      <Text style={styles.note}>Public naam sharing abhi approved policy ke bina band hai.</Text>
      {!!error && <Text style={styles.error}>{error}</Text>}
    </View>;
  }
  if (stage === "sending") {
    return <View style={styles.container}><Text style={styles.title}>Thoda rukhein…</Text><Text style={styles.help}>Photo aur voice note surakshit tareeke se bheje ja rahe hain.</Text></View>;
  }
  if (verificationReady !== true) {
    return <View style={styles.container}>
      <Text style={styles.title}>Pehle pehchaan verify karein</Text>
      <Text style={styles.help}>Shikayat darj karne se pehle pehchaan verification zaroori hai.</Text>
      <Link href="/verify" style={styles.button}>✅  Verification shuru karein</Link>
      <Text style={styles.note}>Aapki pehchaan ke bina complaint submit nahi hogi.</Text>
    </View>;
  }
  if (!permission?.granted) {
    return <View style={styles.container}><Text style={styles.title}>Photo zaroori hai</Text><Text style={styles.help}>Issue ki abhi photo lein. Gallery se photo nahi li jayegi.</Text><Pressable style={styles.button} onPress={requestPermission}><Text style={styles.buttonText}>Camera ki ijazat dein</Text></Pressable></View>;
  }
  if (stage === "photo") {
    return <View style={styles.cameraPage}><CameraView ref={cameraRef} style={styles.camera} facing="back" /><View style={styles.cameraFooter}><Text style={styles.cameraHelp}>Issue ko frame mein laayein</Text><Pressable style={styles.shutter} onPress={capturePhoto}><Text style={styles.shutterText}>Photo lein</Text></Pressable></View></View>;
  }
  return <ScrollView contentContainerStyle={styles.container}>
    <Text style={styles.step}>Step {stage === "category" ? "2" : stage === "voice" ? "3" : "4"} / 4</Text>
    {stage === "category" ? <>
      <Text style={styles.title}>Problem kis baat ki hai?</Text>
      <Text style={styles.help}>Tasveer dekhkar ek nishaan chunein. Naam padhna zaroori nahi hai.</Text>
      <View style={styles.categoryGrid}>
        {categories.map((category) => (
          <Pressable
            key={category.code}
            accessibilityRole="button"
            accessibilityLabel={`${category.label_hi}. ${category.spoken_hi}`}
            onPress={() => chooseCategory(category)}
            style={styles.categoryCard}
          >
            <Text style={styles.categoryIcon}>{category.icon}</Text>
            <Text style={styles.categoryLabel}>{category.label_hi}</Text>
          </Pressable>
        ))}
      </View>
      {!categories.length && <Text style={styles.error}>Categories load nahi hui. Internet jodkar dobara koshish karein.</Text>}
    </> : stage === "voice" ? <>
      <Text style={styles.title}>Apni baat bolkar batayein</Text>
      <Text style={styles.help}>Chhoti voice note banayein. Isse officer ko baat samajhne mein madad milegi.</Text>
      {selectedCategory && <Text style={styles.selectedCategory}>{selectedCategory.icon} {selectedCategory.label_hi}</Text>}
      <Pressable style={styles.button} onPress={recorderState.isRecording ? stopVoice : startVoice}><Text style={styles.buttonText}>{recorderState.isRecording ? "Voice note rokhein" : "Voice note shuru karein"}</Text></Pressable>
      {recorderState.isRecording && <Text style={styles.recording}>● Record ho raha hai ({Math.round(recorderState.durationMillis / 1000)} sec)</Text>}
    </> : <>
      <Text style={styles.title}>{draft ? "Sunkar pakka karein" : "Bhejne se pehle dekhein"}</Text>
      <Text style={styles.help}>{draft ? "AI Neta ne aapki baat is tarah samjhi hai:" : "Photo aur voice note ke saath yeh baat bheji jayegi:"}</Text>
      <TextInput multiline value={description} onChangeText={(value) => { setDescription(value); setDraft(null); Speech.stop(); }} placeholder="Bolkar batayein; chahein toh yahan likh bhi sakte hain" style={styles.textarea} />
      {draft && draft.issue_type && draft.description && <View style={styles.readBack}><Text style={styles.readBackTitle}>Issue: {draft.issue_type}</Text><Text style={styles.readBackText}>{draft.description}</Text><Pressable style={styles.secondaryButton} onPress={() => speakDraft(draft)}><Text style={styles.secondaryButtonText}>🔊  Dobara sunayein</Text></Pressable></View>}
      <Pressable style={styles.button} onPress={reviewOrSubmit} disabled={draftLoading}><Text style={styles.buttonText}>{draftLoading ? "Samjha ja raha hai…" : draft?.issue_type && draft.description ? "Haan, shikayat bhejein" : "Baat samjha kar dikhayein"}</Text></Pressable>
    </>}
    {!!error && <Text style={styles.error}>{error}</Text>}
  </ScrollView>;
}

const styles = StyleSheet.create({
  container: { flexGrow: 1, padding: 28, paddingTop: 76, backgroundColor: "#FFFDF7" },
  cameraPage: { flex: 1, backgroundColor: "#17221D" },
  camera: { flex: 1 },
  cameraFooter: { padding: 24, alignItems: "center", backgroundColor: "#17221D" },
  cameraHelp: { color: "white", fontSize: 18, marginBottom: 16 },
  shutter: { backgroundColor: "#F3B63F", paddingVertical: 18, paddingHorizontal: 40, borderRadius: 14 },
  shutterText: { color: "#17221D", fontSize: 20, fontWeight: "800" },
  step: { color: "#0B6E4F", fontWeight: "800", letterSpacing: 1 },
  title: { marginTop: 14, fontSize: 32, lineHeight: 39, fontWeight: "800", color: "#17221D" },
  help: { marginTop: 18, fontSize: 19, lineHeight: 29, color: "#385449" },
  button: { marginTop: 30, padding: 19, borderRadius: 14, backgroundColor: "#0B6E4F" },
  buttonText: { textAlign: "center", color: "white", fontSize: 18, fontWeight: "800" },
  secondaryButton: { marginTop: 16, padding: 16, borderRadius: 14, borderWidth: 2, borderColor: "#0B6E4F" },
  secondaryButtonText: { textAlign: "center", color: "#0B6E4F", fontSize: 17, fontWeight: "800" },
  readBack: { marginTop: 22, padding: 18, borderRadius: 14, backgroundColor: "#E7F3ED" },
  readBackTitle: { fontSize: 19, fontWeight: "800", color: "#0B6E4F" },
  readBackText: { marginTop: 8, fontSize: 18, lineHeight: 26, color: "#17221D" },
  recording: { marginTop: 20, color: "#A52A2A", fontSize: 18, textAlign: "center" },
  selectedCategory: { marginTop: 20, color: "#0B6E4F", fontSize: 20, fontWeight: "800", textAlign: "center" },
  categoryGrid: { flexDirection: "row", flexWrap: "wrap", gap: 12, marginTop: 28 },
  categoryCard: { width: "47%", minHeight: 132, borderRadius: 16, borderWidth: 2, borderColor: "#B6C5BE", backgroundColor: "white", alignItems: "center", justifyContent: "center", padding: 12 },
  categoryIcon: { fontSize: 42 },
  categoryLabel: { marginTop: 8, color: "#17221D", fontSize: 17, fontWeight: "800", textAlign: "center" },
  textarea: { marginTop: 24, minHeight: 130, borderWidth: 1, borderColor: "#B6C5BE", borderRadius: 12, padding: 16, fontSize: 18, textAlignVertical: "top", backgroundColor: "white" },
  error: { marginTop: 20, color: "#A52A2A", fontSize: 16, lineHeight: 24 },
  receipt: { marginTop: 24, padding: 20, backgroundColor: "#E7F3ED", color: "#0B6E4F", fontSize: 18, fontWeight: "800" },
  note: { marginTop: 20, color: "#5D6D65", fontSize: 16, lineHeight: 24 },
});
