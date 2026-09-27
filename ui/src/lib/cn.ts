export type ClassValue = string | false | null | undefined | 0;

/** Склейка классов без лишних зависимостей. */
export function cn(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(" ");
}
