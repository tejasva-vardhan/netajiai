# AI Neta greenfield web

This is the canonical Next.js App Router surface for the redesign. Deploy
`apps/web` as the public/operator web application.

## Current slice

- Public landing page with low-literacy-friendly Hindi/Hinglish copy.
- Public receipt-token tracking at `/track`, backed by
  `GET /api/v1/public/complaints/{tracking_token}`.
- Policy-gated aggregate accountability view at `/transparency`, backed by
  `GET /api/v1/public/transparency`. It shows only status, execution-zone,
  escalation, and mapping counts; it never shows case IDs, citizen data,
  complaint text, contacts, precise locations, or evidence. The API flag is
  disabled by default until the redaction and publication policy is approved.
- When citizen OIDC is configured, the same `/track` flow can perform an
  authenticated, ownership-checked lookup for a private timeline and the
  three closure outcomes (`fully_solved`, `partially_solved`, or `not_solved`).
  The public token view stays read-only and redacted; a token is kept only in
  browser session storage while returning from sign-in.
- Tracking results use low-literacy icon/color status equivalents and a
  browser-provided Hindi speech playback action when the device supports the
  Web Speech API; the API remains the only source of status facts. The
  implementation sets the BCP 47 `hi-IN` utterance language and falls back to
  the visual/text presentation when speech synthesis is unavailable. See the
  [Web Speech API reference](https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API).
- Installable PWA shell with a narrowly scoped offline fallback for public
  pages/assets. The service worker never caches API responses, receipt tokens,
  complaint data, or authenticated state.
- Operator control tower at `/admin` using a provider-neutral OIDC
  Authorization Code + PKCE flow. Access tokens remain in the current page
  runtime only; the backend remains authoritative for roles and capabilities.
  The redacted control tower also exposes the pending `mapping_in_progress`
  queue; it does not invent contacts or dispatch outbound communication.
- Moderator/admin accounts can review staged, source-cited scheme records from
  the control tower. Approval is the only action that makes a record available
  to grounded scheme answers; the web surface does not invent scheme content.
- The admin route fails closed when OIDC is not configured and the service
  worker never caches `/admin` or its callback.
- Citizen complaint filing is available at `/file` behind public OIDC and
  persisted identity verification. It uses camera-only browser capture,
  browser GPS, microphone recording, direct object-storage upload grants, and
  citizen/idempotency-bound capture sessions. Photo and audio upload keys stay
  stable across retry attempts until that capture is replaced, preventing
  duplicate evidence assets after transient failures. Citizens can select a pictogram
  category and submit an audio-only description; the bounded voice-draft API
  produces a read-back that must be confirmed before submission. Browser
  evidence is labelled separately from native attestation and remains
  `review_required` by default; it must not be described as trusted native
  capture. If review pauses filing, the same screen rechecks the existing
  citizen-owned evidence IDs after operator approval instead of re-uploading
  the files. After submission, the citizen must explicitly confirm the
  private-by-default disclosure choice before opening tracking; public-name
  sharing is not offered while the approved policy flag is disabled.

## Local setup

```bash
npm install
cp .env.example .env.local
npm run dev
```

Set `NEXT_PUBLIC_API_BASE_URL` to the greenfield API origin. The local Compose
profile uses `http://localhost:8001`; use an HTTPS API
origin in staging/production and configure CORS on the backend for the web
origin. The public tracking token is a capability; do not put it in analytics,
logs, or URLs other than the deliberate tracking request.

For a self-hosted production image, pass the public build-time variables to
the standalone Docker build and run the resulting image behind HTTPS:

```bash
docker build \
  --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.gov.in \
  -t ai-neta-web apps/web
docker run --rm -p 3000:3000 ai-neta-web
```

The public OIDC values are optional for public-only deployments but must be
provided as build arguments before enabling citizen or operator sign-in.

## Local activation notes

Global launch gates are maintained in
[`../docs/ACTION_REQUIRED.md`](../docs/ACTION_REQUIRED.md).

- **Web deployment:** create the production hosting project, set the HTTPS
  `NEXT_PUBLIC_API_BASE_URL`, configure the backend allowed origin, and verify
  `npm run build` in the same Node/Next versions used by deployment. Serve the
  site over HTTPS so browser PWA/service-worker rules apply, and bump the
  `CACHE_NAME` in `public/sw.js` when changing the cached public shell.
- **Operator control tower activation:** register a public OIDC client with
  the exact HTTPS callback `/admin/auth/callback` and logout URL, set
  `NEXT_PUBLIC_OIDC_ISSUER`, `NEXT_PUBLIC_OIDC_CLIENT_ID`, and the approved
  scope, configure backend CORS and the provider's `roles` claim for
  `operator`, `admin`, or `moderator`, then validate the capability matrix and
  session/logout policy in staging. No client secret belongs in the browser.
- **Citizen filing activation:** register a separate public OIDC redirect at
  `/auth/callback`, set `NEXT_PUBLIC_OIDC_CITIZEN_REDIRECT_URI` and approved
  scopes, enable backend `WEB_CAPTURE_ENABLED=true`, generate a shared
  `WEB_CAPTURE_SESSION_HMAC_KEY` of at least 32 bytes, and verify browser
  camera/GPS/microphone permissions over HTTPS. Keep
  `WEB_CAPTURE_REVIEW_REQUIRED=true` until approved media inspection and
  browser-capture policy allows direct verification; native mobile remains the
  trusted-capture route.
- **Citizen tracking activation:** use the same public OIDC client for
  `/auth/callback`, verify that the API accepts the provider's citizen subject
  and scopes, and test cross-citizen receipt lookup in staging. Without this
  configuration, `/track` intentionally provides only the public-safe receipt
  projection.
- **Public transparency activation:** obtain product/privacy/legal approval
  for aggregate suppression, redaction, freshness, and retention; then set
  `PUBLIC_TRANSPARENCY_ENABLED=true` and the approved
  `PUBLIC_TRANSPARENCY_POLICY_VERSION` in the backend deployment. The page
  remains an explicit action-required notice while the flag is disabled.
