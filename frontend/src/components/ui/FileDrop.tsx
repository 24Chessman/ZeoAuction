import { useId, useRef, useState, type DragEvent, type ReactNode } from "react";
import { FileText, ImageIcon, RefreshCw, UploadCloud, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";

export interface FileRules {
  accept: string[]; // MIME types
  maxBytes: number;
}

/** The same checks the KYC service makes (type and size); the server still sniffs the bytes. */
export function checkFile(file: File, rules: FileRules): string | null {
  if (!rules.accept.includes(file.type)) return "Use a JPEG, PNG or PDF file";
  if (file.size > rules.maxBytes) return `The file is larger than ${formatBytes(rules.maxBytes)}`;
  return null;
}

interface FileDropProps {
  label: string;
  description?: ReactNode;
  required?: boolean;
  file: File | null;
  rules: FileRules;
  disabled?: boolean;
  error?: string | null;
  onChange: (file: File | null, error: string | null) => void;
}

export function FileDrop({ label, description, required, file, rules, disabled, error, onChange }: FileDropProps) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const id = useId();

  const take = (picked: File | undefined) => {
    if (!picked) return;
    onChange(picked, checkFile(picked, rules));
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (!disabled) take(event.dataTransfer.files[0]);
  };

  const isImage = file?.type.startsWith("image/");

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between">
        <span id={`${id}-label`} className="text-[13px] font-medium text-ink">{label}</span>
        <span className="text-2xs text-ink-faint">{required ? "Required" : "Optional"}</span>
      </div>
      {file ? (
        <div className={cn("flex items-center gap-3 rounded-xl border bg-surface p-3", error ? "border-danger" : "border-line-strong")}>
          <span className={cn("grid size-10 shrink-0 place-items-center rounded-lg", error ? "bg-danger-soft text-danger" : "bg-brand-soft text-brand-ink")}>
            {isImage ? <ImageIcon className="size-5" aria-hidden /> : <FileText className="size-5" aria-hidden />}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-ink">{file.name}</p>
            <p className={cn("text-xs", error ? "text-danger" : "text-ink-faint")}>{error ?? `${formatBytes(file.size)} · ${file.type || "unknown type"}`}</p>
          </div>
          <button type="button" onClick={() => input.current?.click()} disabled={disabled} className="rounded-lg p-2 text-ink-faint hover:bg-surface-2 hover:text-ink" aria-label={`Replace ${label}`}>
            <RefreshCw className="size-4" />
          </button>
          <button type="button" onClick={() => onChange(null, null)} disabled={disabled} className="rounded-lg p-2 text-ink-faint hover:bg-surface-2 hover:text-danger" aria-label={`Remove ${label}`}>
            <X className="size-4" />
          </button>
        </div>
      ) : (
        <button
          type="button"
          disabled={disabled}
          onClick={() => input.current?.click()}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          aria-describedby={`${id}-desc`}
          className={cn(
            "group flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-7 text-center transition-colors",
            dragging ? "border-brand bg-brand-soft/60" : error ? "border-danger/60 bg-danger-soft/30" : "border-line-strong bg-surface-2/40 hover:border-brand/60 hover:bg-brand-soft/30",
            disabled && "cursor-not-allowed opacity-60",
          )}
        >
          <span className="grid size-10 place-items-center rounded-full bg-surface shadow-card ring-1 ring-line transition-transform group-hover:-translate-y-0.5">
            <UploadCloud className="size-5 text-brand-ink" aria-hidden />
          </span>
          <span className="text-sm font-medium text-ink">
            Drop a file or <span className="text-brand-ink underline-offset-2 group-hover:underline">browse</span>
          </span>
          <span id={`${id}-desc`} className="text-xs text-ink-faint">{description ?? `JPEG, PNG or PDF · up to ${formatBytes(rules.maxBytes)}`}</span>
          {error && <span className="text-xs text-danger">{error}</span>}
        </button>
      )}
      <input
        ref={input}
        type="file"
        className="sr-only"
        accept={rules.accept.join(",")}
        aria-labelledby={`${id}-label`}
        tabIndex={-1}
        onChange={(event) => {
          take(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
    </div>
  );
}
