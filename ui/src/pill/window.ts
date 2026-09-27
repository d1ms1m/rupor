// Окно пилюли в Tauri: позиция (pill_position), перетаскивание, «сквозные» клики
// вне капсулы, скрытие по pill_enabled. Вне Tauri все функции — пустышки.
import { inTauri, resetPillPosition } from "../lib/tauri";

type TauriWindowModule = typeof import("@tauri-apps/api/window");

let mod: TauriWindowModule | null = null;
async function win(): Promise<TauriWindowModule | null> {
  if (!inTauri()) return null;
  if (!mod) mod = await import("@tauri-apps/api/window");
  return mod;
}

let userDrag = false;
let movedSinceDrag = false;
let programmaticUntil = 0;
let lastApplied = "";
let pillVisible = true;

/** Позиция по умолчанию (запасной вариант, если Rust-команда недоступна). */
async function defaultPosition(m: TauriWindowModule): Promise<[number, number] | null> {
  const w = m.getCurrentWindow();
  const mon = (await m.primaryMonitor()) ?? (await m.currentMonitor());
  if (!mon) return null;
  const size = await w.outerSize();
  const wa = mon.workArea ?? { position: mon.position, size: mon.size };
  const margin = Math.round(12 * mon.scaleFactor);
  const x = Math.round(wa.position.x + (wa.size.width - size.width) / 2);
  const y = Math.round(wa.position.y + wa.size.height - size.height - margin);
  return [x, y];
}

async function onSomeMonitor(m: TauriWindowModule, x: number, y: number): Promise<boolean> {
  const w = m.getCurrentWindow();
  const size = await w.outerSize();
  const cx = x + size.width / 2;
  const cy = y + size.height / 2;
  const mons = await m.availableMonitors();
  return mons.some(
    (mon) =>
      cx >= mon.position.x &&
      cx < mon.position.x + mon.size.width &&
      cy >= mon.position.y &&
      cy < mon.position.y + mon.size.height,
  );
}

/**
 * Позиция из настроек. При старте окно уже поставил Rust (по settings.json), поэтому
 * первый вызов только запоминает значение; дальше реагируем на изменения:
 * null → вернуть вниз по центру (команда reset_pill_position), [x, y] → переставить.
 */
export async function applyPillPosition(pos: [number, number] | null): Promise<void> {
  const m = await win();
  if (!m) return;
  const key = JSON.stringify(pos);
  const first = lastApplied === "";
  if (key === lastApplied || userDrag) return;
  lastApplied = key;
  if (first) return;
  try {
    programmaticUntil = Date.now() + 600;
    if (pos && (await onSomeMonitor(m, pos[0], pos[1]))) {
      await m.getCurrentWindow().setPosition(new m.PhysicalPosition(pos[0], pos[1]));
      return;
    }
    try {
      await resetPillPosition();
    } catch {
      const target = await defaultPosition(m);
      if (target) await m.getCurrentWindow().setPosition(new m.PhysicalPosition(target[0], target[1]));
    }
  } catch (e) {
    console.warn("pill position", e);
  }
}

/** pill_enabled: скрыть или показать окно (показ — без активации, это держит Rust). */
export async function setPillVisible(visible: boolean): Promise<void> {
  const m = await win();
  if (!m) return;
  try {
    const w = m.getCurrentWindow();
    pillVisible = visible;
    if (!visible) await w.hide();
    else if (!(await w.isVisible())) await w.show();
  } catch (e) {
    console.warn("pill visibility", e);
  }
}

/** Начать перетаскивание окна (вызывать из pointerdown/pointermove). */
export async function startPillDrag(): Promise<void> {
  const m = await win();
  if (!m) return;
  userDrag = true;
  movedSinceDrag = false;
  // если окно так и не сдвинулось (клик без переноса) — снять флаг
  setTimeout(() => {
    if (!movedSinceDrag) userDrag = false;
  }, 1500);
  try {
    await m.getCurrentWindow().startDragging();
  } catch (e) {
    userDrag = false;
    console.warn("startDragging", e);
  }
}

/** Следить за перемещением окна: по окончании перетаскивания — сохранить позицию. */
export async function watchPillMoves(save: (pos: [number, number]) => void): Promise<() => void> {
  const m = await win();
  if (!m) return () => {};
  let timer: ReturnType<typeof setTimeout> | null = null;
  const w = m.getCurrentWindow();
  const un = await w.onMoved(({ payload }) => {
    if (Date.now() < programmaticUntil || !userDrag) return;
    movedSinceDrag = true;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      userDrag = false;
      const pos: [number, number] = [Math.round(payload.x), Math.round(payload.y)];
      lastApplied = JSON.stringify(pos);
      save(pos);
    }, 500);
  });
  return () => {
    if (timer) clearTimeout(timer);
    un();
  };
}

/**
 * Прозрачная часть окна 360×96 не должна перехватывать клики: пока курсор вне капсулы,
 * окно игнорирует мышь (setIgnoreCursorEvents), курсор опрашиваем раз в 80 мс.
 */
export async function startPassthrough(getRect: () => DOMRect | null): Promise<() => void> {
  const m = await win();
  if (!m) return () => {};
  const w = m.getCurrentWindow();
  let ignoring: boolean | null = null;
  let stopped = false;
  let failures = 0;
  let pos = await w.outerPosition().catch(() => null);
  let scale = await w.scaleFactor().catch(() => 1);
  const unMove = await w.onMoved(({ payload }) => {
    pos = payload;
  });
  const unScale = await w.onScaleChanged(({ payload }) => {
    scale = payload.scaleFactor;
  });

  const set = async (ignore: boolean) => {
    if (ignoring === ignore) return;
    ignoring = ignore;
    await w.setIgnoreCursorEvents(ignore);
  };

  const tick = async () => {
    if (stopped) return;
    if (!pillVisible) {
      // окно скрыто — опрашивать курсор незачем
      setTimeout(() => void tick(), 500);
      return;
    }
    try {
      const rect = getRect();
      if (!rect || !pos || userDrag) {
        await set(false);
      } else {
        const c = await m.cursorPosition();
        const margin = 6 * scale;
        const left = pos.x + rect.left * scale - margin;
        const top = pos.y + rect.top * scale - margin;
        const right = pos.x + rect.right * scale + margin;
        const bottom = pos.y + rect.bottom * scale + margin;
        const inside = c.x >= left && c.x <= right && c.y >= top && c.y <= bottom;
        await set(!inside);
      }
      failures = 0;
    } catch (e) {
      // нет прав на API окна — оставляем окно обычным (кликабельным)
      if (++failures > 5) {
        stopped = true;
        console.warn("pill passthrough disabled", e);
        await w.setIgnoreCursorEvents(false).catch(() => {});
        return;
      }
    }
    setTimeout(() => void tick(), 80);
  };
  void tick();

  return () => {
    stopped = true;
    unMove();
    unScale();
    void w.setIgnoreCursorEvents(false).catch(() => {});
  };
}
