import * as AuthSession from "expo-auth-session";
import * as WebBrowser from "expo-web-browser";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import {
  getAccessToken,
  getIdentityVerificationStatus,
  IdentityVerificationStatus,
  saveAccessToken,
  startIdentityVerification,
} from "../src/api";

WebBrowser.maybeCompleteAuthSession();

const issuer = process.env.EXPO_PUBLIC_OIDC_ISSUER?.trim() ?? "";
const clientId = process.env.EXPO_PUBLIC_OIDC_CLIENT_ID?.trim() ?? "";
const scopes = (process.env.EXPO_PUBLIC_OIDC_SCOPES ?? "openid profile")
  .split(/[ ,]+/)
  .map((scope) => scope.trim())
  .filter(Boolean);

export default function VerifyScreen() {
  if (!issuer || !clientId) {
    return <SetupRequired />;
  }
  return <ConfiguredVerification issuer={issuer} clientId={clientId} />;
}

function SetupRequired() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Pehchaan verify karein</Text>
      <Text style={styles.help}>
        Sign-in provider abhi app mein configure nahi hai. Staging ya production
        ke liye OIDC issuer aur public client ID set karna zaroori hai.
      </Text>
      <Text style={styles.note}>
        App mein koi client secret nahi rakha jaata. Yeh setup backend/provider
        administrator karega.
      </Text>
    </View>
  );
}

function ConfiguredVerification({ issuer, clientId }: { issuer: string; clientId: string }) {
  const discovery = AuthSession.useAutoDiscovery(issuer);
  const redirectUri = useMemo(
    () => AuthSession.makeRedirectUri({ scheme: "aineta", path: "auth/callback" }),
    [],
  );
  const [request, response, promptAsync] = AuthSession.useAuthRequest(
    {
      clientId,
      redirectUri,
      responseType: AuthSession.ResponseType.Code,
      scopes,
      usePKCE: true,
    },
    discovery,
  );
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [verification, setVerification] = useState<IdentityVerificationStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const processedCode = useRef<string | null>(null);

  async function refreshStatus() {
    try {
      setError("");
      setVerification(await getIdentityVerificationStatus());
    } catch (statusError) {
      setError(statusError instanceof Error ? statusError.message : "Status nahi mil saka.");
    }
  }

  useEffect(() => {
    void getAccessToken().then((token) => {
      setAccessToken(token);
      if (token) void refreshStatus();
    });
  }, []);

  useEffect(() => {
    if (!response || response.type !== "success" || !response.params.code || !request) return;
    if (processedCode.current === response.params.code) return;
    processedCode.current = response.params.code;
    if (!discovery?.tokenEndpoint || !request.codeVerifier) {
      setError("Sign-in provider ka token setup poora nahi hai.");
      return;
    }
    setBusy(true);
    setError("");
    void AuthSession.exchangeCodeAsync(
      {
        clientId,
        code: response.params.code,
        redirectUri,
        scopes,
        extraParams: { code_verifier: request.codeVerifier },
      },
      discovery,
    )
      .then(async (tokenResponse) => {
        await saveAccessToken(tokenResponse.accessToken);
        setAccessToken(tokenResponse.accessToken);
        setVerification(await getIdentityVerificationStatus());
      })
      .catch((signInError: unknown) => {
        setError(signInError instanceof Error ? signInError.message : "Sign-in nahi ho saka.");
      })
      .finally(() => setBusy(false));
  }, [response, request, discovery, clientId, redirectUri]);

  async function startVerification() {
    setBusy(true);
    setError("");
    try {
      const authorization = await startIdentityVerification();
      await WebBrowser.openBrowserAsync(authorization.authorization_url);
      await refreshStatus();
    } catch (verificationError) {
      setError(
        verificationError instanceof Error
          ? verificationError.message
          : "Pehchaan verification shuru nahi ho saki.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!accessToken) {
    return (
      <View style={styles.container}>
        <Text style={styles.title}>Pehle sign-in karein</Text>
        <Text style={styles.help}>
          Secure sign-in ke baad aapki pehchaan verify hogi.
        </Text>
        <Pressable
          style={styles.button}
          disabled={!request || !discovery || busy}
          onPress={() => void promptAsync()}
        >
          <Text style={styles.buttonText}>{busy ? "Rukhein…" : "Sign-in karein"}</Text>
        </Pressable>
        {!!error && <Text style={styles.error}>{error}</Text>}
      </View>
    );
  }

  const verified = verification?.status === "verified";
  const providerLabel = verification?.provider === "temporary" ? "local interim verification" : "DigiLocker";
  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.title}>Pehchaan ka status</Text>
      <Text style={styles.help}>
        {verified
          ? `Aapki ${providerLabel} poori ho gayi hai. Ab shikayat darj kar sakte hain.`
          : "Complaint bhejne se pehle pehchaan verification poori karni hogi."}
      </Text>
      <View style={styles.statusCard}>
        <Text style={styles.statusTitle}>
          {verification?.status === "verified"
            ? "Verified ✅"
            : verification?.status === "pending"
              ? "Verification pending"
              : verification?.status === "rejected"
                ? "Verification dobara karein"
                : "Verification abhi nahi hui"}
        </Text>
        <Text style={styles.note}>
          App sirf verification status rakhti hai; provider ke documents ya raw claims nahi.
        </Text>
      </View>
      {!verified && (
        <Pressable style={styles.button} disabled={busy} onPress={() => void startVerification()}>
          <Text style={styles.buttonText}>{busy ? "Rukhein…" : "Verification kholein"}</Text>
        </Pressable>
      )}
      <Pressable style={styles.secondaryButton} disabled={busy} onPress={() => void refreshStatus()}>
        <Text style={styles.secondaryButtonText}>Status dobara dekhein</Text>
      </Pressable>
      {!!error && <Text style={styles.error}>{error}</Text>}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flexGrow: 1, padding: 28, paddingTop: 76, backgroundColor: "#FFFDF7" },
  title: { fontSize: 32, lineHeight: 39, fontWeight: "800", color: "#17221D" },
  help: { marginTop: 18, fontSize: 19, lineHeight: 29, color: "#385449" },
  note: { marginTop: 18, fontSize: 16, lineHeight: 24, color: "#5D6D65" },
  button: { marginTop: 30, padding: 19, borderRadius: 14, backgroundColor: "#0B6E4F" },
  buttonText: { textAlign: "center", color: "white", fontSize: 18, fontWeight: "800" },
  secondaryButton: { marginTop: 16, padding: 17, borderRadius: 14, borderWidth: 2, borderColor: "#0B6E4F" },
  secondaryButtonText: { textAlign: "center", color: "#0B6E4F", fontSize: 17, fontWeight: "800" },
  statusCard: { marginTop: 24, padding: 20, borderRadius: 14, backgroundColor: "#E7F3ED" },
  statusTitle: { fontSize: 21, fontWeight: "800", color: "#0B6E4F" },
  error: { marginTop: 20, color: "#A52A2A", fontSize: 16, lineHeight: 24 },
});
