import { LoaderCircle } from "lucide-react";
import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  PropsWithChildren,
} from "react";
import { twMerge } from "tailwind-merge";

export function cn(...values: Array<string | false | null | undefined>) {
  return twMerge(values.filter(Boolean).join(" "));
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "default" | "small";
  busy?: boolean;
};

export function Button({
  className,
  variant = "primary",
  size = "default",
  busy,
  children,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn("button", `button-${variant}`, `button-${size}`, className)}
      disabled={disabled || busy}
      {...props}
    >
      {busy && <LoaderCircle className="spin" size={17} aria-hidden />}
      {children}
    </button>
  );
}

export function Card({
  className,
  children,
  ...props
}: PropsWithChildren<HTMLAttributes<HTMLDivElement>>) {
  return (
    <div className={cn("card", className)} {...props}>
      {children}
    </div>
  );
}

export function StatusDot({
  tone,
}: {
  tone: "good" | "warn" | "muted" | "active";
}) {
  return <span className={cn("status-dot", `status-dot-${tone}`)} aria-hidden />;
}

export function FieldLabel({
  children,
  htmlFor,
}: PropsWithChildren<{ htmlFor?: string }>) {
  return (
    <label className="field-label" htmlFor={htmlFor}>
      {children}
    </label>
  );
}
