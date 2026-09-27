// Кэш дорогих запросов на время сессии (проверка CUDA, баланс ключа).
const store = new Map<string, { at: number; p: Promise<unknown> }>();

export function cached<T>(key: string, ttlMs: number, fn: () => Promise<T>): Promise<T> {
  const hit = store.get(key);
  if (hit && Date.now() - hit.at < ttlMs) return hit.p as Promise<T>;
  const p = fn();
  store.set(key, { at: Date.now(), p });
  p.catch(() => store.delete(key));
  return p;
}

export function invalidate(key: string): void {
  store.delete(key);
}
