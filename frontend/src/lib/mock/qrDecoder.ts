// QR decoding for mock mode with zxing-wasm, the WebAssembly build of zxing-cpp (the engine
// services/kyc uses). Loaded on first use, and the .wasm is served by Vite rather than a CDN.

import { prepareZXingModule, readBarcodes } from "zxing-wasm/reader";
import wasmUrl from "zxing-wasm/reader/zxing_reader.wasm?url";

prepareZXingModule({
  overrides: { locateFile: (path: string, prefix: string) => (path.endsWith(".wasm") ? wasmUrl : prefix + path) },
});

/** The text of every QR code in the photo. */
export async function readQrCodes(image: Blob): Promise<string[]> {
  const codes = await readBarcodes(image, { formats: ["QRCode"], tryHarder: true, maxNumberOfSymbols: 4 });
  return codes.filter((code) => code.isValid && code.text).map((code) => code.text);
}
