// «Словарь учится на правках»: уведомления ядра notice с action dict_undo / dict_add
// и кнопки «Отменить» / «Добавить» (dict_learn_undo / dict_learn_accept).
//
// Одно и то же уведомление ядро шлёт во все окна (пилюля и главное окно). Чтобы правку
// нельзя было отменить дважды, а страница «Словарь» сразу увидела изменения, окна
// сообщают друг другу о нажатых кнопках через BroadcastChannel (у окон Tauri общий
// источник tauri.localhost). Нет BroadcastChannel — каждое окно живёт само по себе.
//
// Отметка «уже нажато» относится к одному уведомлению, а не к правке навсегда: ядро может
// прислать байт-в-байт такое же уведомление ещё раз (добавили термин кнопкой, удалили его
// на странице «Словарь» и снова так же исправили). Поэтому каждое пришедшее уведомление
// снимает старую отметку (learnNoticeArrived) — иначе его кнопка молча ничего бы не сделала.
import type { DictItem, LearnData, NoticeEvent } from "./types";
import { backend, call } from "./ws";

export type LearnAction = "dict_undo" | "dict_add";

/** notice про словарь: action dict_undo / dict_add и data с правкой. */
export interface LearnNotice extends NoticeEvent {
  action: LearnAction;
  data: LearnData;
}

export function isLearnNotice(n: NoticeEvent): n is LearnNotice {
  if (n.action !== "dict_undo" && n.action !== "dict_add") return false;
  const d = n.data;
  return Boolean(d) && typeof d?.term === "string" && typeof d.variant === "string";
}

/** Ключ правки: одинаковый во всех окнах для одного и того же уведомления. */
export function learnKey(n: LearnNotice): string {
  const d = n.data;
  return [n.action, d.term.toLowerCase(), d.variant.toLowerCase(), d.id ?? "", d.created ? 1 : 0].join("\u0001");
}

/** Та же правка (вариант → термин), независимо от действия. */
export function sameCorrection(a: LearnNotice, b: LearnNotice): boolean {
  return (
    a.data.term.toLowerCase() === b.data.term.toLowerCase() &&
    a.data.variant.toLowerCase() === b.data.variant.toLowerCase()
  );
}

type Listener = (key: string, action: LearnAction) => void;

interface Resolution {
  action: LearnAction;
  /** performance.now() этого окна, когда кнопку нажали здесь или узнали о нажатии в другом окне. */
  at: number;
}

const resolved = new Map<string, Resolution>();
/**
 * Уведомление пришло так скоро после нажатия — это то же самое уведомление, просто в это окно
 * оно дошло позже, чем весть из другого окна. Новая такая же правка раньше прийти не может:
 * нужно удалить термин, снова надиктовать и исправить, а ядро оценивает правку в конце наблюдения.
 */
const SAME_NOTICE_MS = 3000;
const inflight = new Map<string, Promise<DictItem | null>>();
const listeners = new Set<Listener>();
const dictListeners = new Set<() => void>();
const CHANNEL = "rupor-learn";

interface ChannelMsg {
  key: string;
  action: LearnAction;
}

let channel: BroadcastChannel | null = null;
// В демо-режиме у каждой вкладки свой мок-бэкенд — синхронизировать нечего.
if (!backend.mock) {
  try {
    channel = new BroadcastChannel(CHANNEL);
    channel.onmessage = (e: MessageEvent<unknown>) => {
      const m = e.data as Partial<ChannelMsg> | null;
      if (!m || typeof m.key !== "string" || (m.action !== "dict_undo" && m.action !== "dict_add")) return;
      mark(m.key, m.action, false);
    };
  } catch {
    channel = null;
  }
}

function mark(key: string, action: LearnAction, broadcast: boolean): void {
  if (resolved.has(key)) return;
  resolved.set(key, { action, at: performance.now() });
  if (resolved.size > 200) {
    const first = resolved.keys().next().value;
    if (first !== undefined) resolved.delete(first);
  }
  if (broadcast) {
    try {
      channel?.postMessage({ key, action } satisfies ChannelMsg);
    } catch {
      // окно закрывается — не страшно
    }
  }
  for (const fn of [...listeners]) fn(key, action);
  for (const fn of [...dictListeners]) fn();
}

/**
 * Пришло уведомление ядра — звать до isResolved / resolveLearn (пилюля и тост главного окна).
 * Новое уведомление — новое событие: прежняя отметка «уже нажато» с тем же ключом к нему не
 * относится. Ядро шлёт уведомление всем окнам сразу, так что дедупликация между окнами не
 * страдает; а если в другом окне нажали только что, это то же уведомление — отметку оставляем.
 */
export function learnNoticeArrived(n: LearnNotice): void {
  const key = learnKey(n);
  const r = resolved.get(key);
  if (r && performance.now() - r.at > SAME_NOTICE_MS) resolved.delete(key);
}

/** Уже нажали «Отменить» / «Добавить» на этом уведомлении (в этом или другом окне). */
export function isResolved(n: LearnNotice): boolean {
  return resolved.has(learnKey(n));
}

/**
 * Нажата кнопка уведомления: dict_undo → dict_learn_undo, dict_add → dict_learn_accept.
 * Повторное нажатие (например, в другом окне) ядро не зовёт.
 */
export function resolveLearn(n: LearnNotice): Promise<DictItem | null> {
  const key = learnKey(n);
  if (resolved.has(key)) return Promise.resolve(null);
  // Двойной клик или кнопка в тосте, пока ядро ещё отвечает, — тот же запрос, а не второй.
  const pending = inflight.get(key);
  if (pending) return pending;
  const d = n.data;
  const run = async (): Promise<DictItem | null> => {
    let item: DictItem | null = null;
    if (n.action === "dict_undo") {
      await call("dict_learn_undo", { term: d.term, variant: d.variant, id: d.id, created: d.created });
    } else {
      item = await call("dict_learn_accept", { term: d.term, variant: d.variant });
    }
    mark(key, n.action, true);
    return item;
  };
  const p = run().finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

/** Кнопку уведомления нажали (здесь или в другом окне). */
export function onLearnResolved(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** Словарь изменился из-за кнопок уведомлений (здесь или в другом окне). */
export function onDictChanged(fn: () => void): () => void {
  dictListeners.add(fn);
  return () => {
    dictListeners.delete(fn);
  };
}
