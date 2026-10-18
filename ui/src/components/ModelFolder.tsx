// Папка моделей Whisper (settings.model_dir): путь, «Обзор…», «По умолчанию» и перенос уже
// скачанной модели в новую папку (model_dir_set). Общий для «Настройки → Диктовка» и мастера.
//
// Папка — в формате кэша Hugging Face (models--org--name/…), её же можно отдать другим
// программам на faster-whisper как download_root. Перенос идёт в фоне: прогресс — события
// progress what="model" (как у загрузки), по окончании ядро присылает settings с новым
// model_dir и notice «Модель перенесена…» (тост показывает App). Пока модель переносится,
// диктует прежняя загруженная модель.
import { AnimatePresence, motion } from "framer-motion";
import { Check, CircleAlert, Download, FolderOpen, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { cn } from "../lib/cn";
import { useEvent, useLoad } from "../lib/hooks";
import { errorText } from "../lib/hub";
import { useCore } from "../lib/store";
import { inTauri, pickFolder } from "../lib/tauri";
import { call } from "../lib/ws";
import { Button, Input } from "./ui/controls";
import { Badge, ProgressBar } from "./ui/display";
import { Modal, Tooltip } from "./ui/overlay";

/** Пути Windows равны без учёта регистра, вида разделителя и «\» в конце. */
export function samePath(a: string, b: string): boolean {
  const norm = (p: string) => p.trim().replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();
  return norm(a) === norm(b);
}

interface Job {
  pct: number;
  text: string;
  error: string | null;
  done: boolean;
}

export function ModelFolder({
  disabled,
  showDownloads = true,
  onChanged,
}: {
  /** Снаружи известно, что модель качается (мастер — ещё до первого события progress). */
  disabled?: boolean;
  /**
   * Показывать и прогресс загрузки модели (смена модели в настройках качает её сюда). В
   * мастере у загрузки своя строка — там только перенос.
   */
  showDownloads?: boolean;
  /** Папка сменилась или перенос закончился — родителю перечитать setup_status. */
  onChanged?: () => void;
}) {
  const { settings } = useCore();
  const setup = useLoad(() => call("setup_status"), [settings?.model, settings?.model_dir]);
  const [draft, setDraft] = useState<string | null>(null);
  const [pending, setPendingState] = useState<string | null>(null);
  // Окно «Перенести модель?» закрывается с анимацией, и всё это время его кнопки живы с
  // прежним замыканием, где pending — путь. Кнопки читают ref: второй щелчок (двойной по
  // «Перенести») видит, что первый его уже сбросил
  const pendingRef = useRef<string | null>(null);
  const setPending = (p: string | null) => {
    pendingRef.current = p;
    setPendingState(p);
  };
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Перенос, начатый здесь: все события progress what="model" до done — его (пока модель
  // переносится, ядро не качает её, слот «model» занят)
  const [move, setMoveState] = useState<Job | null>(null);
  const moveRef = useRef<Job | null>(null);
  const setMove = (j: Job | null) => {
    moveRef.current = j;
    setMoveState(j);
  };
  // Загрузка модели (не перенос): идущая или неудавшаяся (done с error)
  const [dl, setDl] = useState<Job | null>(null);

  useEvent("progress", (p) => {
    if (p.what !== "model") return;
    const job: Job = { pct: p.pct, text: p.text, error: p.error, done: p.done };
    if (moveRef.current && !moveRef.current.done) {
      // удачный перенос: тост «Модель перенесена…» пришлёт ядро, здесь полоса просто уходит
      setMove(p.done && !p.error ? null : job);
    } else {
      // пошла загрузка — итог прошлого переноса к ней не относится, полоса — её
      if (moveRef.current) setMove(null);
      // удачная загрузка уходит, ошибка остаётся до новой загрузки, смены модели или папки
      setDl(p.done && !p.error ? null : job);
    }
    if (p.done) {
      setup.reload();
      onChanged?.();
    }
  });
  // Ядро перезапустилось — перенос или загрузка умерли вместе с ним, события done не будет
  useEvent("hello", () => {
    if (moveRef.current && !moveRef.current.done) setMove(null);
    setDl(null);
  });
  // Удачный перенос ядро закрепляет новым model_dir (событие settings): полоса уходит, даже
  // если последнее событие progress потерялось. Итог прошлого переноса или загрузки (ошибка)
  // к другой модели или папке не относится
  const modelDir = settings?.model_dir;
  const model = settings?.model;
  const last = useRef({ modelDir, model });
  useEffect(() => {
    const dirChanged = last.current.modelDir !== modelDir;
    if (!dirChanged && last.current.model === model) return;
    last.current = { modelDir, model };
    if (moveRef.current && (dirChanged || moveRef.current.done)) setMove(null);
    setDl((d) => (d?.done ? null : d));
  }, [modelDir, model]);

  if (!settings) return null;
  const st = setup.data;
  const effective = st?.model_dir ?? "";
  const moving = Boolean(move && !move.done);
  const downloading = Boolean(dl && !dl.done);
  const busy = Boolean(disabled) || sending || moving || downloading;
  const value = draft ?? effective;
  const edited = draft !== null && !samePath(draft, effective);
  const tauri = inTauri();

  const send = async (path: string, doMove: boolean) => {
    setPending(null);
    // Перенос отсюда ещё идёт: второй ядро отклонило бы («переносится»), а catch ниже сбросил
    // бы полосу настоящего переноса
    if (doMove && moveRef.current && !moveRef.current.done) return;
    setErr(null);
    setSending(true);
    // прошлая неудача переноса или загрузки больше не показывается
    setDl((d) => (d?.done ? null : d));
    if (doMove) setMove({ pct: 0, text: t("modelFolder.moving"), error: null, done: false });
    else if (moveRef.current?.done) setMove(null);
    try {
      const r = await call("model_dir_set", { path, move: doMove });
      if (!r.moving && moveRef.current && !moveRef.current.done) setMove(null);
      setDraft(null);
      setup.reload();
      onChanged?.();
    } catch (e) {
      if (moveRef.current && !moveRef.current.done) setMove(null);
      setErr(t("modelFolder.changeFailed", { error: errorText(e) }));
    } finally {
      setSending(false);
    }
  };

  /** Новая папка ("" — по умолчанию): скачанную модель — спросить, переносить ли. */
  const choose = (raw: string) => {
    const path = raw.trim();
    setErr(null);
    if (!st) return;
    const target = path === "" ? st.model_dir_default : path;
    if (samePath(target, st.model_dir)) {
      setDraft(null);
      // «По умолчанию», а в настройке явный путь к той же папке: переносить нечего, сохраняем
      // "" — папка снова следует за HF_HOME / HF_HUB_CACHE
      if (path === "" && settings.model_dir !== "") void send("", false);
      return;
    }
    if (st.model_ready) setPending(path);
    else void send(path, false);
  };

  const browse = async () => {
    try {
      const picked = await pickFolder(effective || undefined, t("modelFolder.browseTitle"));
      if (picked) {
        setDraft(picked);
        choose(picked);
      }
    } catch (e) {
      setErr(t("modelFolder.changeFailed", { error: errorText(e) }));
    }
  };

  /** Кнопка окна переноса: путь — из pendingRef (см. выше), не из замыкания. */
  const confirmMove = (doMove: boolean) => {
    const path = pendingRef.current;
    if (path !== null) void send(path, doMove);
  };

  const job = move ?? (showDownloads ? dl : null);
  const jobShown = Boolean(job && (!job.done || job.error));

  return (
    <div data-testid="model-folder">
      <div className="flex items-center gap-2">
        <Input
          aria-label={t("modelFolder.label")}
          value={value}
          placeholder={t("modelFolder.placeholder")}
          disabled={busy || !st}
          spellCheck={false}
          title={value}
          onChange={(e) => {
            setDraft(e.target.value);
            setErr(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && draft !== null) {
              // без preventDefault тот же Enter (keypress) нажал бы «Перенести» в открывшемся окне
              e.preventDefault();
              choose(draft);
            }
            if (e.key === "Escape") setDraft(null);
          }}
          className="min-w-0 flex-1 [&_input]:font-mono [&_input]:text-[12.5px]"
        />
        {edited && (
          <Button size="sm" variant="primary" disabled={busy} loading={sending} onClick={() => choose(draft ?? "")}>
            {t("modelFolder.apply")}
          </Button>
        )}
        {tauri && (
          <Button
            size="sm"
            variant="secondary"
            icon={<FolderOpen className="size-4" />}
            disabled={busy || !st}
            onClick={() => void browse()}
          >
            {t("modelFolder.browse")}
          </Button>
        )}
        {settings.model_dir !== "" && st && (
          <Tooltip content={t("modelFolder.resetHint", { path: st.model_dir_default })}>
            <Button
              size="sm"
              variant="ghost"
              icon={<RotateCcw className="size-4" />}
              disabled={busy}
              onClick={() => {
                setDraft(null);
                choose("");
              }}
            >
              {t("modelFolder.reset")}
            </Button>
          </Tooltip>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-subtle">
        {st ? (
          <>
            <Badge tone={settings.model_dir === "" ? "neutral" : "accent"}>
              {settings.model_dir === "" ? t("modelFolder.isDefault") : t("modelFolder.isCustom")}
            </Badge>
            <span className={cn("flex items-center gap-1", st.model_ready && "text-success")}>
              {st.model_ready ? <Check className="size-3.5" /> : <Download className="size-3.5" />}
              {st.model_ready
                ? t("modelFolder.modelHere", { model: settings.model })
                : t("modelFolder.modelMissing", { model: settings.model })}
            </span>
            {busy && !sending && <span>{t("modelFolder.busy")}</span>}
          </>
        ) : setup.error && !setup.loading ? (
          <span className="flex items-center gap-1 text-danger">
            <CircleAlert className="size-3.5 shrink-0" />
            {t("modelFolder.statusFailed", { error: setup.error })}
          </span>
        ) : null}
      </div>

      {err && (
        <div role="alert" className="mt-2 flex items-start gap-1.5 text-[12.5px] text-danger selectable">
          <CircleAlert className="mt-0.5 size-3.5 shrink-0" />
          <span>{err}</span>
        </div>
      )}

      <AnimatePresence initial={false}>
        {jobShown && job && (
          <motion.div
            key="job"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="pt-3">
              <ProgressBar value={job.pct} tone={job.error ? "danger" : "accent"} />
              <div className={cn("mt-1.5 flex justify-between gap-3 text-[12px]", job.error ? "text-danger" : "text-subtle")}>
                <span className="min-w-0 truncate" title={job.error ?? job.text}>
                  {job.error
                    ? t(move ? "modelFolder.moveFailed" : "modelFolder.downloadFailed", { error: job.error })
                    : job.text}
                </span>
                <span className="tabular shrink-0">{Math.round(job.pct)}%</span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <Modal
        open={pending !== null}
        onClose={() => setPending(null)}
        title={t("modelFolder.moveTitle")}
        width={500}
        footer={
          <>
            <Button variant="ghost" onClick={() => setPending(null)}>
              {t("common.cancel")}
            </Button>
            <Button variant="secondary" onClick={() => confirmMove(false)}>
              {t("modelFolder.noMove")}
            </Button>
            <Button variant="primary" autoFocus onClick={() => confirmMove(true)}>
              {t("modelFolder.move")}
            </Button>
          </>
        }
      >
        <p>{t("modelFolder.moveBody")}</p>
        {pending !== null && st && (
          <div className="mt-3 space-y-2 rounded-xl bg-surface-2 p-3 text-[12.5px]">
            <PathLine label={t("modelFolder.moveFrom")} path={st.model_dir} />
            <PathLine label={t("modelFolder.moveTo")} path={pending === "" ? st.model_dir_default : pending} />
          </div>
        )}
        <p className="mt-3 text-[12.5px] text-subtle">{t("modelFolder.noMoveHint")}</p>
      </Modal>
    </div>
  );
}

function PathLine({ label, path }: { label: string; path: string }) {
  return (
    <div>
      <div className="text-[11.5px] font-medium text-subtle">{label}</div>
      <div className="break-all font-mono text-[12px] text-fg selectable">{path}</div>
    </div>
  );
}
