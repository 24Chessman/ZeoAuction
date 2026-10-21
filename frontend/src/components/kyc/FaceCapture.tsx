import { useCallback, useEffect, useRef, useState } from "react";
import { Camera, CameraOff, RotateCcw, ScanFace } from "lucide-react";
import { cn } from "@/lib/cn";
import { Banner, Button } from "@/components/ui";

/**
 * Guided live capture for the face check (services/kyc, app/domain/face.py). The server needs
 * 3–8 frames with exactly one face, and the head has to turn between them: that is its basic
 * liveness check against a photo held up to the camera. So the seller looks straight, then
 * left, then right, and two frames are taken at each prompt. Frames stay in memory and go
 * only to the KYC service.
 */
const PROMPTS = [
  { text: "Look straight at the camera", shots: 2 },
  { text: "Slowly turn your head to the left", shots: 2 },
  { text: "Now slowly to the right", shots: 2 },
] as const;
const TOTAL = PROMPTS.reduce((n, p) => n + p.shots, 0);
const SETTLE_MS = 1100; // time to follow a prompt before the first shot
const SHOT_GAP_MS = 380;

type Phase = "idle" | "starting" | "ready" | "capturing" | "done";

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function cameraError(error: unknown): string {
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "Camera access was blocked. Allow it in the browser's address bar, then try again.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No camera was found on this device.";
  if (name === "NotReadableError") return "The camera is in use by another app. Close it and try again.";
  return "The camera could not be started.";
}

interface FaceCaptureProps {
  /** The upload is running; the camera is released. */
  busy: boolean;
  onCaptured: (frames: Blob[]) => void;
}

export function FaceCapture({ busy, onCaptured }: FaceCaptureProps) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const cancelled = useRef(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [prompt, setPrompt] = useState(0);
  const [taken, setTaken] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const stop = useCallback(() => {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
  }, []);

  useEffect(() => {
    cancelled.current = false;
    return () => {
      cancelled.current = true;
      stop();
    };
  }, [stop]);

  const start = async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser can't open the camera here. Use a current browser over HTTPS (or localhost).");
      return;
    }
    setPhase("starting");
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });
      if (cancelled.current) {
        media.getTracks().forEach((track) => track.stop());
        return;
      }
      stream.current = media;
      if (video.current) {
        video.current.srcObject = media;
        await video.current.play().catch(() => undefined);
      }
      setPhase("ready");
    } catch (caught) {
      setError(cameraError(caught));
      setPhase("idle");
    }
  };

  const grab = (canvas: HTMLCanvasElement): Promise<Blob | null> => {
    const el = video.current;
    if (!el || !el.videoWidth) return Promise.resolve(null);
    canvas.width = el.videoWidth;
    canvas.height = el.videoHeight;
    // Unmirrored: the preview is flipped for the seller's comfort, the frames are not.
    canvas.getContext("2d")?.drawImage(el, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.88));
  };

  const capture = async () => {
    setPhase("capturing");
    setTaken(0);
    const canvas = document.createElement("canvas");
    const frames: Blob[] = [];
    for (let i = 0; i < PROMPTS.length; i += 1) {
      setPrompt(i);
      await wait(SETTLE_MS);
      for (let shot = 0; shot < PROMPTS[i].shots; shot += 1) {
        if (cancelled.current) return;
        const frame = await grab(canvas);
        if (frame) frames.push(frame);
        setTaken(frames.length);
        await wait(SHOT_GAP_MS);
      }
    }
    stop();
    if (frames.length < 3) {
      setError("The camera didn't deliver enough frames. Try again.");
      setPhase("idle");
      return;
    }
    setPhase("done");
    onCaptured(frames);
  };

  const live = phase === "ready" || phase === "capturing";
  return (
    <div className="space-y-4">
      <div className="relative mx-auto aspect-[4/3] w-full max-w-md overflow-hidden rounded-4xl bg-midnight shadow-lift">
        <video
          ref={video}
          muted
          playsInline
          aria-label="Your camera"
          className={cn("size-full -scale-x-100 object-cover transition-opacity duration-300", live ? "opacity-100" : "opacity-0")}
        />
        {/* The oval the face should fill; everything around it is dimmed. */}
        <svg viewBox="0 0 400 300" className="pointer-events-none absolute inset-0 size-full" aria-hidden>
          <defs>
            <mask id="face-oval">
              <rect width="400" height="300" fill="white" />
              <ellipse cx="200" cy="140" rx="82" ry="108" fill="black" />
            </mask>
          </defs>
          <rect width="400" height="300" fill="rgb(10 10 24 / 0.55)" mask="url(#face-oval)" />
          <ellipse
            cx="200" cy="140" rx="82" ry="108" fill="none" strokeWidth="3" strokeDasharray={phase === "capturing" ? "0" : "6 7"}
            className={cn("transition-colors duration-300", phase === "capturing" ? "stroke-brand" : "stroke-white/70")}
          />
        </svg>
        {!live && (
          <div className="absolute inset-0 grid place-items-center text-center text-white/80">
            <div className="flex flex-col items-center gap-2 px-6">
              {phase === "done" || busy ? <ScanFace className="size-8" aria-hidden /> : <Camera className="size-8" aria-hidden />}
              <p className="text-sm">{busy ? "Matching your face…" : phase === "done" ? "Captured" : "Camera off"}</p>
            </div>
          </div>
        )}
        {phase === "capturing" && (
          <div className="absolute inset-x-3 bottom-3 rounded-2xl bg-black/60 px-4 py-2.5 text-center backdrop-blur-sm" aria-live="assertive">
            <p className="text-sm font-semibold text-white">{PROMPTS[prompt].text}</p>
            <div className="mt-2 flex justify-center gap-1.5" aria-label={`${taken} of ${TOTAL} frames`}>
              {Array.from({ length: TOTAL }, (_, i) => (
                <span key={i} className={cn("h-1.5 w-5 rounded-full transition-colors", i < taken ? "bg-brand" : "bg-white/25")} />
              ))}
            </div>
          </div>
        )}
      </div>

      {error && <Banner tone="danger" title="Camera problem" live>{error}</Banner>}

      <div className="flex flex-wrap justify-center gap-3">
        {(phase === "idle" || phase === "starting") && (
          <Button onClick={() => void start()} loading={phase === "starting"} disabled={busy} icon={<Camera className="size-4" />}>
            Turn on camera
          </Button>
        )}
        {phase === "ready" && (
          <>
            <Button onClick={() => void capture()} icon={<ScanFace className="size-4" />}>Start face check</Button>
            <Button variant="ghost" onClick={() => { stop(); setPhase("idle"); }} icon={<CameraOff className="size-4" />}>Turn off</Button>
          </>
        )}
        {phase === "done" && !busy && (
          <Button variant="secondary" onClick={() => { setPhase("idle"); void start(); }} icon={<RotateCcw className="size-4" />}>
            Try again
          </Button>
        )}
      </div>
      <p className="text-center text-xs text-ink-faint">
        Good light on your face, no cap or sunglasses, only you in the frame. Frames are sent only to our verification service.
      </p>
    </div>
  );
}
