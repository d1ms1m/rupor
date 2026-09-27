// Общие интерфейсы клиента ядра (настоящего WS и мок-бэкенда).
import type {
  CommandArgs,
  CommandName,
  CommandResult,
  ConnStatus,
  EventMap,
  EventName,
} from "./types";

export interface CallOptions {
  /** Таймаут ответа, мс (по умолчанию 45 000). */
  timeoutMs?: number;
}

export type ArgsTuple<C extends CommandName> = [CommandArgs<C>] extends [void]
  ? [args?: undefined, opts?: CallOptions]
  : [args: CommandArgs<C>, opts?: CallOptions];

export interface Backend {
  readonly mock: boolean;
  start(): void;
  status(): ConnStatus;
  call<C extends CommandName>(cmd: C, ...rest: ArgsTuple<C>): Promise<CommandResult<C>>;
  on<E extends EventName>(event: E, fn: (data: EventMap[E]) => void): () => void;
  onStatus(fn: (s: ConnStatus) => void): () => void;
  /** Только мок: сымитировать диктовку. */
  simulateDictation?: () => void;
}

export class BackendError extends Error {
  readonly cmd: string;
  constructor(message: string, cmd: string) {
    super(message);
    this.name = "BackendError";
    this.cmd = cmd;
  }
}

type Handler = (data: never) => void;

/** Типизированная шина событий. */
export class EventHub<M extends object> {
  private map = new Map<keyof M, Set<Handler>>();

  on<E extends keyof M>(event: E, fn: (data: M[E]) => void): () => void {
    let set = this.map.get(event);
    if (!set) {
      set = new Set();
      this.map.set(event, set);
    }
    const h = fn as unknown as Handler;
    set.add(h);
    return () => {
      set.delete(h);
    };
  }

  emit<E extends keyof M>(event: E, data: M[E]): void {
    const set = this.map.get(event);
    if (!set) return;
    for (const h of [...set]) {
      try {
        (h as unknown as (d: M[E]) => void)(data);
      } catch (e) {
        console.error("event handler", String(event), e);
      }
    }
  }
}

export function errorText(e: unknown): string {
  if (e instanceof Error) return e.message;
  if (typeof e === "string") return e;
  return String(e);
}
