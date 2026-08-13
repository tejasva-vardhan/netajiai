import * as Crypto from "expo-crypto";
import { File } from "expo-file-system";

export type CapturedFile = {
  uri: string;
  contentType: string;
  byteSize: number;
};

export async function describeFile(uri: string, contentType: string): Promise<CapturedFile> {
  const file = new File(uri);
  if (!file.exists) throw new Error("The captured file is no longer available on this device");
  return { uri, contentType, byteSize: file.size ?? 0 };
}

export async function sha256File(uri: string): Promise<string> {
  const file = new File(uri);
  const digest = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, await file.bytes());
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

export async function sha256Blob(blob: Blob): Promise<string> {
  const digest = await Crypto.digest(
    Crypto.CryptoDigestAlgorithm.SHA256,
    new Uint8Array(await blob.arrayBuffer()),
  );
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

export async function fileAsBlob(uri: string): Promise<Blob> {
  const response = await fetch(uri);
  if (!response.ok) throw new Error("Could not read the captured file");
  return response.blob();
}

export interface CaptureAttestationProvider {
  attest(capture: CapturedFile): Promise<string>;
}

export class ConfiguredCaptureAttestationProvider implements CaptureAttestationProvider {
  async attest(capture: CapturedFile): Promise<string> {
    if (process.env.EXPO_PUBLIC_CAPTURE_ATTESTATION_MODE !== "development") {
      throw new Error("Verified capture is not configured for this build");
    }
    return JSON.stringify({
      mode: "development-only",
      uri_digest: await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, capture.uri),
      captured_at: new Date().toISOString(),
    });
  }
}
