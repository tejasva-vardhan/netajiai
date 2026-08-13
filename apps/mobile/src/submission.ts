import { File } from "expo-file-system";
import { completeEvidencePart, completeEvidenceUpload, createComplaint, createEvidenceUpload, createVoiceComplaintDraft, LocationCapture, uploadFile, uploadPart } from "./api";
import { ConfiguredCaptureAttestationProvider, describeFile, fileAsBlob, sha256Blob, sha256File } from "./capture";
import type { Capture, QueuedCapture } from "./queue";

export class EvidenceReviewPendingError extends Error {
  readonly code = "review_pending";

  constructor() {
    super("Evidence is awaiting human review");
    this.name = "EvidenceReviewPendingError";
  }
}

export class EvidenceRejectedError extends Error {
  readonly code = "evidence_rejected";

  constructor() {
    super("Evidence was rejected");
    this.name = "EvidenceRejectedError";
  }
}

async function uploadAndComplete(
  assetType: "photo" | "audio",
  uri: string,
  contentType: string,
  location: LocationCapture,
  attestation: string,
  idempotencyKey: string,
): Promise<string> {
  const file = await describeFile(uri, contentType);
  const upload = await createEvidenceUpload({
    assetType,
    contentType: file.contentType,
    byteSize: file.byteSize,
    sha256: await sha256File(file.uri),
    captureAttestation: attestation,
    location,
    idempotencyKey,
  });
  if (upload.status === "review_required") throw new EvidenceReviewPendingError();
  if (upload.status === "rejected") throw new EvidenceRejectedError();
  if (upload.status !== "verified") {
    if (upload.upload_mode === "multipart") {
      if (!upload.part_size || !upload.part_count || upload.parts.length !== upload.part_count) {
        throw new Error("The evidence storage provider returned incomplete multipart metadata");
      }
      const fileObject = new File(file.uri);
      for (const grant of upload.parts) {
        if (upload.completed_parts.includes(grant.part_number)) continue;
        const start = (grant.part_number - 1) * upload.part_size;
        const part = fileObject.slice(start, Math.min(start + upload.part_size, file.byteSize), file.contentType);
        const etag = await uploadPart(grant, part);
        await completeEvidencePart(
          upload.evidence_asset_id,
          grant.part_number,
          { etag, sha256: await sha256Blob(part), byteSize: part.size },
        );
      }
    } else {
      if (!upload.upload_url || upload.upload_method !== "PUT") {
        throw new Error("The evidence storage provider did not return a usable upload URL");
      }
      await uploadFile(upload, await fileAsBlob(file.uri));
    }
    const completion = await completeEvidenceUpload(upload.evidence_asset_id);
    if (completion.status === "review_required") throw new EvidenceReviewPendingError();
    if (completion.status !== "verified") throw new EvidenceRejectedError();
  }
  return upload.evidence_asset_id;
}

export async function submitCapturedComplaint(capture: QueuedCapture) {
  const attestationProvider = new ConfiguredCaptureAttestationProvider();
  const photo = await describeFile(capture.photoUri, "image/jpeg");
  const audio = await describeFile(capture.audioUri, "audio/mp4");
  const photoAttestation = await attestationProvider.attest(photo);
  const audioAttestation = await attestationProvider.attest(audio);
  const location = {
    latitude: capture.latitude,
    longitude: capture.longitude,
    accuracy_m: capture.accuracyM,
    source: "device_gps" as const,
  };
  const photoAssetId = await uploadAndComplete(
    "photo",
    photo.uri,
    photo.contentType,
    location,
    photoAttestation,
    `capture:${capture.id}:photo`,
  );
  const audioAssetId = await uploadAndComplete(
    "audio",
    audio.uri,
    audio.contentType,
    location,
    audioAttestation,
    `capture:${capture.id}:audio`,
  );
  return createComplaint({
    issueType: capture.issueType,
    description: capture.description,
    language: capture.language,
    evidenceAssetIds: [photoAssetId, audioAssetId],
    idempotencyKey: `capture:${capture.id}:complaint`,
  });
}

export async function createVoiceDraftForCapture(capture: Capture) {
  const attestationProvider = new ConfiguredCaptureAttestationProvider();
  const audio = await describeFile(capture.audioUri, "audio/mp4");
  const audioAttestation = await attestationProvider.attest(audio);
  const location = {
    latitude: capture.latitude,
    longitude: capture.longitude,
    accuracy_m: capture.accuracyM,
    source: "device_gps" as const,
  };
  const audioAssetId = await uploadAndComplete(
    "audio",
    audio.uri,
    audio.contentType,
    location,
    audioAttestation,
    `capture:${capture.id}:audio`,
  );
  return createVoiceComplaintDraft({
    audioAssetId,
    language: capture.language,
    idempotencyKey: `capture:${capture.id}:voice-draft`,
  });
}
