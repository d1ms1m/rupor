// Поля настроек, которые сохраняются по завершении ввода (blur / Enter).
import { Minus, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "../lib/cn";
import { Input } from "./ui/controls";

export function CommitInput({
  value,
  onCommit,
  placeholder,
  className,
  mono,
  type = "text",
}: {
  value: string;
  onCommit: (v: string) => void;
  placeholder?: string;
  className?: string;
  mono?: boolean;
  type?: "text" | "password";
}) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const commit = () => {
    if (v !== value) onCommit(v.trim());
  };
  return (
    <Input
      type={type}
      value={v}
      placeholder={placeholder}
      onChange={(e) => setV(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") setV(value);
      }}
      className={cn(className, mono && "[&_input]:font-mono [&_input]:text-[12.5px]")}
      spellCheck={false}
    />
  );
}

export function Stepper({
  value,
  min,
  max,
  step = 1,
  onChange,
  suffix,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  suffix?: string;
}) {
  const set = (n: number) => onChange(Math.max(min, Math.min(max, n)));
  return (
    <div className="inline-flex h-9 items-center rounded-[10px] border border-line bg-surface-2">
      <button
        type="button"
        onClick={() => set(value - step)}
        disabled={value <= min}
        className="flex h-full w-8 items-center justify-center rounded-l-[10px] text-muted transition-colors hover:bg-surface-3 hover:text-fg disabled:opacity-40"
      >
        <Minus className="size-3.5" />
      </button>
      <span className="tabular min-w-12 px-1 text-center text-[13.5px] font-medium text-fg">
        {value}
        {suffix && <span className="ml-1 text-[12px] font-normal text-subtle">{suffix}</span>}
      </span>
      <button
        type="button"
        onClick={() => set(value + step)}
        disabled={value >= max}
        className="flex h-full w-8 items-center justify-center rounded-r-[10px] text-muted transition-colors hover:bg-surface-3 hover:text-fg disabled:opacity-40"
      >
        <Plus className="size-3.5" />
      </button>
    </div>
  );
}
