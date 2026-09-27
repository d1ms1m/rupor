// Запись хоткея в настройках не должна запускать действия ядра.
//
// Глобальный хук ядра видит нажатия раньше WebView: текущее «Вставить последнее»
// проглатывается и вставляет последний текст в последнее чужое окно, «Скопировать
// последнее» молча перезаписывает буфер, удержание PTT начинает настоящую запись.
// Команда pause снимает хук целиком (hook.paused — события идут мимо машины жестов,
// действий нет), поэтому на время записи ставим ядро на паузу, а потом снимаем её —
// только если до записи паузы не было. Несколько одновременных записей считаются.
import { call } from "./ws";

let holders = 0;
let resumeAfter = false;
let pendingResume = 0; // отправленные, но ещё не отвеченные «снять паузу»
let chain: Promise<unknown> = Promise.resolve();

function send(on: boolean): void {
  if (!on) pendingResume++;
  // по порядку: «снять паузу» не должно обогнать «поставить»
  chain = chain
    .then(() => call("pause", { on }))
    .catch(() => {})
    .then(() => {
      if (!on) pendingResume--;
    });
}

// Окно закрывают или перезагружают посреди записи — не оставляем ядро на паузе.
if (typeof window !== "undefined") {
  window.addEventListener("pagehide", () => {
    if (!resumeAfter) return;
    resumeAfter = false;
    holders = 0;
    call("pause", { on: false }).catch(() => {});
  });
}

/**
 * Заглушить хоткеи ядра на время записи клавиши.
 * paused — стоит ли ядро на паузе сейчас (тогда хук и так выключен, трогать не нужно).
 * Возвращает «отпустить»; повторный вызов безопасен.
 */
export function muteCoreHotkeys(paused: boolean): () => void {
  holders++;
  // Пауза, которую поставили мы сами и уже снимаем, — не пользовательская.
  const userPaused = paused && pendingResume === 0;
  if (holders === 1 && !userPaused && !resumeAfter) {
    resumeAfter = true;
    send(true);
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    holders = Math.max(0, holders - 1);
    if (holders === 0 && resumeAfter) {
      resumeAfter = false;
      send(false);
    }
  };
}
