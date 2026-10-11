import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { AlertCircle } from "lucide-react";
import { cn } from "@/lib/cn";

const control =
  "w-full rounded-xl border bg-surface text-ink placeholder:text-ink-faint transition-[border-color,box-shadow] duration-150 " +
  "focus:border-brand focus:shadow-focus focus:outline-none disabled:cursor-not-allowed disabled:opacity-60";

function controlClasses(invalid: boolean, extra?: string): string {
  return cn(control, invalid ? "border-danger" : "border-line-strong hover:border-ink-faint/60", extra);
}

interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  optional?: boolean;
  className?: string;
  children: (props: { id: string; "aria-invalid": boolean; "aria-describedby"?: string }) => ReactNode;
}

/** Label + control + hint/error, wired for screen readers. */
export function Field({ label, hint, error, optional, className, children }: FieldProps) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="flex items-baseline justify-between text-[13px] font-medium text-ink">
        <span>{label}</span>
        {optional && <span className="text-2xs font-normal text-ink-faint">Optional</span>}
      </label>
      {children({ id, "aria-invalid": Boolean(error), "aria-describedby": describedBy })}
      {error ? (
        <p id={`${id}-error`} className="flex items-start gap-1.5 text-[13px] text-danger" role="alert">
          <AlertCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-[13px] text-ink-faint">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  leading?: ReactNode;
  trailing?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ className, leading, trailing, ...rest }, ref) {
  const invalid = rest["aria-invalid"] === true || rest["aria-invalid"] === "true";
  if (!leading && !trailing) return <input ref={ref} className={controlClasses(invalid, cn("h-11 px-3.5 text-[15px]", className))} {...rest} />;
  return (
    <div className="relative">
      {leading && <span className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-ink-faint">{leading}</span>}
      <input
        ref={ref}
        className={controlClasses(invalid, cn("h-11 text-[15px]", leading ? "pl-9" : "pl-3.5", trailing ? "pr-24" : "pr-3.5", className))}
        {...rest}
      />
      {trailing && <span className="absolute inset-y-0 right-1.5 flex items-center">{trailing}</span>}
    </div>
  );
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  const invalid = rest["aria-invalid"] === true || rest["aria-invalid"] === "true";
  return <textarea ref={ref} className={controlClasses(invalid, cn("min-h-28 px-3.5 py-3 text-[15px] leading-relaxed", className))} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  const invalid = rest["aria-invalid"] === true || rest["aria-invalid"] === "true";
  return (
    <select ref={ref} className={controlClasses(invalid, cn("h-11 appearance-none bg-[length:16px] bg-[right_12px_center] bg-no-repeat px-3.5 pr-10 text-[15px]", className))}
      style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")" }}
      {...rest}
    >
      {children}
    </select>
  );
});
