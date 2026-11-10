import { useEffect, useId, useMemo, useRef, useState, type DragEvent } from "react";
import { ImagePlus, Star, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";
import { checkFile, type FileRules } from "@/components/ui";

/** services/auction-orchestrator app/domain/images.py: the server checks the bytes again. */
export const LISTING_PHOTO_RULES: FileRules = {
  accept: ["image/jpeg", "image/png", "image/webp"],
  extensions: [".jpg", ".jpeg", ".png", ".webp"],
  maxBytes: 5 * 1024 * 1024,
  typeLabel: "JPEG, PNG or WebP",
};
export const MAX_LISTING_PHOTOS = 6;

interface Props {
  files: File[];
  onChange: (files: File[]) => void;
  disabled?: boolean;
  /** Files already uploaded can't be removed here (they belong to the saved draft). */
  locked?: ReadonlySet<File>;
  error?: string | null;
}

/** Up to six listing photos with previews; the first one is the cover. */
export function PhotoPicker({ files, onChange, disabled, locked, error }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const id = useId();
  const previews = useMemo(() => files.map((file) => URL.createObjectURL(file)), [files]);
  useEffect(() => () => previews.forEach((url) => URL.revokeObjectURL(url)), [previews]);

  const add = (picked: FileList | null | undefined) => {
    if (!picked?.length) return;
    const next = [...files];
    let problem: string | null = null;
    for (const file of Array.from(picked)) {
      const fault = checkFile(file, LISTING_PHOTO_RULES);
      if (fault) problem = `${file.name}: ${fault}`;
      else if (next.length >= MAX_LISTING_PHOTOS) problem = `An auction can have at most ${MAX_LISTING_PHOTOS} photos`;
      else next.push(file);
    }
    setRefused(problem);
    onChange(next);
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (!disabled) add(event.dataTransfer.files);
  };

  const makeCover = (index: number) => onChange([files[index], ...files.filter((_, i) => i !== index)]);
  const message = error ?? refused;
  const full = files.length >= MAX_LISTING_PHOTOS;

  return (
    <div className="flex flex-col gap-2">
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3" aria-label="Chosen photos">
        {files.map((file, index) => (
          <li key={`${file.name}-${file.lastModified}-${index}`} className="group relative aspect-[4/3] overflow-hidden rounded-2xl border border-line bg-surface-2">
            <img src={previews[index]} alt={`Photo ${index + 1}: ${file.name}`} className="size-full object-cover" />
            {index === 0 ? (
              <span className="absolute left-2 top-2 rounded-full bg-black/70 px-2 py-0.5 text-2xs font-semibold text-white">Cover</span>
            ) : (
              // Once photos are uploaded, their order is fixed by the server.
              !disabled && !locked?.size && (
                <button
                  type="button"
                  onClick={() => makeCover(index)}
                  className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-full bg-surface/90 px-2 py-0.5 text-2xs font-medium text-ink opacity-0 shadow-card transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
                >
                  <Star className="size-3" aria-hidden /> Make cover
                </button>
              )
            )}
            {!disabled && !locked?.has(file) && (
              <button
                type="button"
                onClick={() => onChange(files.filter((_, i) => i !== index))}
                aria-label={`Remove ${file.name}`}
                className="absolute right-2 top-2 grid size-7 place-items-center rounded-full bg-surface/90 text-ink-muted shadow-card hover:text-danger"
              >
                <X className="size-4" />
              </button>
            )}
            <span className="absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/60 to-transparent px-2 pb-1.5 pt-4 text-2xs text-white">
              {formatBytes(file.size)}
            </span>
          </li>
        ))}
        {!full && (
          <li>
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
                "flex aspect-[4/3] w-full flex-col items-center justify-center gap-1.5 rounded-2xl border-2 border-dashed px-3 text-center transition-colors",
                dragging ? "border-brand bg-brand-soft/60" : message ? "border-danger/60 bg-danger-soft/30" : "border-line-strong bg-surface-2/40 hover:border-brand/60 hover:bg-brand-soft/30",
                disabled && "cursor-not-allowed opacity-60",
              )}
            >
              <ImagePlus className="size-6 text-brand-ink" aria-hidden />
              <span className="text-sm font-medium text-ink">{files.length ? "Add more" : "Add photos"}</span>
              <span id={`${id}-desc`} className="text-2xs text-ink-faint">
                {LISTING_PHOTO_RULES.typeLabel} · up to {formatBytes(LISTING_PHOTO_RULES.maxBytes)}
              </span>
            </button>
          </li>
        )}
      </ul>
      <p className={cn("text-xs", message ? "text-danger" : "text-ink-faint")} role={message ? "alert" : undefined}>
        {message ?? `${files.length} of ${MAX_LISTING_PHOTOS} photos. The first one is the cover; listings without photos show a stock picture.`}
      </p>
      <input
        ref={input}
        type="file"
        multiple
        className="sr-only"
        accept={[...LISTING_PHOTO_RULES.accept, ...(LISTING_PHOTO_RULES.extensions ?? [])].join(",")}
        aria-label="Add photos"
        tabIndex={-1}
        onChange={(event) => {
          add(event.target.files);
          event.target.value = "";
        }}
      />
    </div>
  );
}
