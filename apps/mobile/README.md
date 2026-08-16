# AI Neta mobile citizen app

This is the greenfield citizen capture surface and consumes the versioned API
under `backend/app`.

The mobile landing page has one citizen entry point into the conversation. The
chat router keeps general talk, filing, verification, and status in the same
session; camera/microphone permission and native capture screens open only when
the next action requires a device capability.

Expo web is a preview target only: its tab-scoped session-storage fallback is
not a secure native credential store. Signed Android/iOS builds use
`expo-secure-store` and the SQLCipher queue. If verification opens a separate
provider screen, returning to Chat rechecks the identity status and resumes the
pending filing handoff in the same conversation.

The first flow includes a one-time spoken Hindi/Hinglish explainer for first-time users, a signed-in, tap-assisted AI Neta conversation surface, and the verified complaint path: native camera capture, foreground GPS, a server-owned versioned pictogram category choice with spoken labels, mandatory voice note, server-side voice-to-structured-draft extraction when the citizen does not type, optional text fallback, spoken/tap read-back confirmation, explicit private-by-default disclosure consent after filing, evidence upload, complaint submission, and opaque receipt-token tracking. The latest receipt capability is kept in platform secure storage so a citizen can reopen tracking and tap to hear/check it without retyping a token; older/shared tokens can still be entered manually. Conversation sessions are persisted by the backend and the mobile client keeps the session capability in SecureStore; failed chat turns expose a retry with the same idempotency key so a lost response cannot create a duplicate turn. Narrow backend handlers decide whether to hand off to verification, filing, tracking, or grounded scheme information. Chat responses and complaint status can be spoken aloud, and status also has icon/color equivalents. When a department reports a fix, the authenticated citizen tracking screen offers large tap choices for “kaam poora ho gaya”, “thoda hua, baaki chahiye”, or “kaam nahi hua”; the outcome is sent with a stable idempotency key and the public receipt view remains read-only. Partial and unsolved outcomes keep the case in follow-up rather than closing it. The category catalogue is cached in SecureStore for a previously loaded low-connectivity snapshot; the API remains its source of truth. The explainer adds only its onboarding flag and category snapshot; the separate offline queue may retain complaint text, coordinates, and media references until a server receipt or explicit expiry. When the receipt belongs to the signed-in citizen, tracking also shows the private lifecycle timeline; an invalid or different citizen's receipt remains limited to the public-safe status. The app never offers gallery selection for verified evidence. The live STT adapter and dialect-quality gate remain backend deployment requirements.

Native capture uses a recent bounded device location when available and falls
back to balanced-accuracy location when a fresh high-accuracy fix is
unavailable, so a permitted device does not get stuck before taking a photo.

## Local setup

```bash
npm install
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.10:8001 \
EXPO_PUBLIC_OIDC_ISSUER=http://192.168.1.10:8080/realms/aineta \
EXPO_PUBLIC_OIDC_CLIENT_ID=aineta-mobile \
EXPO_PUBLIC_OIDC_SCOPES="openid profile" \
npx expo start
```

Use a real device for camera, location, audio, and file behavior. `localhost` from a phone means the phone itself, not the development machine.

## Local activation notes

Global launch gates are maintained in
[`../docs/ACTION_REQUIRED.md`](../docs/ACTION_REQUIRED.md).

- **Backend URL:** set `EXPO_PUBLIC_API_BASE_URL` to the HTTPS staging/production API URL. Verify `/health` from the device before testing submission.
- **Authenticated session:** register the OIDC public client and the `aineta://auth/callback` redirect for each signed build, then set `EXPO_PUBLIC_OIDC_ISSUER`, `EXPO_PUBLIC_OIDC_CLIENT_ID`, and the approved scopes. The app uses authorization-code + PKCE and stores the access/refresh token pair only in `expo-secure-store`; API calls refresh once through the provider when the access token expires. No client secret belongs in the app.
- **Conversation handoff:** the chat keeps the current complaint text and recognized category in a local handoff for at most 30 minutes while the native camera/microphone capability screen is open. It is cleared after a confirmed server receipt or when the citizen starts a new conversation; the handoff is not a server identity or workflow authority.
- **Identity provider:** local Compose uses the clearly labelled temporary identity handoff and seeded Keycloak account claims. Production must configure the approved DigiLocker Requester transport, callback URL, scopes, claim mapping, and retention policy; the temporary provider is never a production identity proof.
- **Native capture attestation:** replace `ConfiguredCaptureAttestationProvider` with the approved Android/iOS attestation adapter before production. Development mode is intentionally rejected by the production default and must not be enabled in a production build.
- **Speech transcription:** the local backend composition uses Deepgram for verified audio. Configure its language/model policy and bounded quotas, then validate noisy Hindi/English/Hinglish audio and uncertain-transcription human fallback before production. The app calls `/api/v1/complaints/voice-draft` only after the audio asset is server-verified; no speech provider secret belongs in the app.
- **EAS project/build:** create the Expo/EAS project, configure Android and iOS identifiers, signing, privacy declarations, and release channels. Run a development build; Expo Go is not a production verification target.
- **Storage and upload test:** configure a staging object-store adapter and test single PUT and multipart completion, part ETag exposure through storage CORS, retry/duplicate idempotency, malware/clarity inspection, and cleanup of abandoned local files.
- **Offline worker:** the SQLite queue records interrupted captures. The app
  registers an Expo Background Task with a 15-minute minimum interval and
  retains the foreground retry fallback. OS scheduling is best-effort, so a
  capture is not reported as submitted until the server returns a receipt.
  Validate this on signed Android/iOS development builds; Expo Go and iOS
  simulators are not production evidence for background execution.
- **Offline privacy:** the native queue uses SQLCipher with a per-install key
  kept in `expo-secure-store`. Build the `expo-sqlite` config plugin into signed
  Android/iOS binaries and verify that interrupted complaint text, coordinates,
  and queue metadata cannot be read from an extracted database. The encrypted
  queue is versioned as `aineta-capture-queue-v2.db`; any pre-release plaintext
  development database must be cleared during device testing, and a future
  production migration must preserve or explicitly expire old queued captures.
  Each queued capture is also bound to the local authentication session that
  created it; foreground/background retry skips captures from another account
  session rather than submitting them under the wrong identity.
  This follows the pinned Expo SDK 57 [`expo-sqlite` SQLCipher configuration](https://docs.expo.dev/versions/v57.0.0/sdk/sqlite/); SQLCipher is not an Expo Go capability.
  Photo/audio files remain in OS-managed app storage until upload; verify
  Android file-based encryption, iOS data protection, and cleanup of abandoned
  files in signed device builds before production.
- **Local policy gate — Product/privacy:** approve the maximum local queue age
  for `capture_queue` records and the expiry behavior before a signed
  production build. The decision must cover deletion of the SQLCipher row and
  its OS-managed photo/audio files, the next-open message shown to the citizen,
  and whether a capture can ever be retried after sign-out or session change.
  Record the approved policy/version in `apps/mobile/src/queue.native.ts`, then
  verify expiry and cleanup on signed Android and iOS builds. No retention
  period is invented in the current implementation.
- **Dependency security:** the lockfile is aligned with the latest compatible
  Expo SDK 57 patch set (`expo@57.0.12`, `expo-router@57.0.12`, and matching
  Expo modules), and `npx expo-doctor` passes all 20 checks. As of 11 August
  2026, `npm audit --omit=dev` still reports 14 high and 7 moderate
  transitive Metro/Expo/React Native advisories; its automatic fix proposes
  incompatible major downgrades (including Expo 53 and React Native 0.72).
  Do not run `npm audit fix --force`. Recheck upstream Expo/Metro fixes and
  complete a signed-build security review before production release.

When the app opens, it attempts a foreground retry using stable per-capture
idempotency keys and registers the OS background task. A successful foreground
or background retry saves the server receipt token in secure storage so the
citizen can use the last-receipt status action after reopening the app. The
queue is retained when authentication, attestation, storage, or network checks
fail. Background execution is opportunistic and cannot guarantee immediate
delivery; only a server receipt confirms submission.

No real API credentials or provider secrets belong in this directory.
