// Мастер первого запуска: полноэкранный, шаги с прогрессом и анимацией.
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleAlert,
  Cpu,
  Download,
  FolderDown,
  Gauge,
  HardDrive,
  Keyboard,
  Languages,
  Laptop,
  Mic,
  MonitorSmartphone,
  Power,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Square,
  Timer,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import { HotkeyCapture } from "../components/HotkeyCapture";
import { KeyManager } from "../components/KeyManager";
import { LevelBar, LiveWave } from "../components/Level";
import { Logo } from "../components/Logo";
import { ModelFolder } from "../components/ModelFolder";
import { Button, IconButton, Segmented, Switch } from "../components/ui/controls";
import { Badge, KeyCombo, ProgressBar, Spinner } from "../components/ui/display";
import { Select, type SelectOption } from "../components/ui/select";
import { useToast } from "../components/ui/toast";
import { getLocale, languageName, LOCALES, NATIVE_NAMES, systemLocale, t, tIn, tp, type Locale, type TKey } from "../i18n";
import { cached, invalidate } from "../lib/cache";
import { cn } from "../lib/cn";
import { fmtDecimal, fmtMb, fmtMs, fmtSeconds } from "../lib/format";
import { useEvent, useLoad, useMicMonitor } from "../lib/hooks";
import { errorText } from "../lib/hub";
import { keyLabel } from "../lib/keys";
import { useCore } from "../lib/store";
import { autostartEnabled, inTauri, setAutostart } from "../lib/tauri";
import type {
  DictationLanguage,
  DownloadWhat,
  ModelOption,
  ModelRating,
  ModelRecommend,
  ProgressEvent,
  Settings,
  SettingsPatch,
  TestRecordResult,
} from "../lib/types";
import { call } from "../lib/ws";

const STEPS = ["language", "welcome", "mic", "model", "test", "hotkeys", "ai", "autostart", "done"] as const;
type Step = (typeof STEPS)[number];

export function Wizard({ onDone }: { onDone: () => void }) {
  const { settings, updateSettings } = useCore();
  const [i, setI] = useState(0);
  const [dir, setDir] = useState(1);
  const [canNext, setCanNext] = useState(true);
  // Модель уже выбрана в этом проходе мастера (рекомендацию не подставлять повторно)
  const modelPicked = useRef(false);
  const step: Step = STEPS[i] ?? "language";

  const go = (delta: number) => {
    setDir(delta);
    setCanNext(true);
    setI((x) => Math.max(0, Math.min(STEPS.length - 1, x + delta)));
  };

  const finish = async () => {
    await updateSettings({ first_run_done: true });
    onDone();
  };

  if (!settings) return null;

  return (
    <div className="relative flex h-full flex-col overflow-hidden bg-layer">
      <div
        className="pointer-events-none absolute inset-x-0 -top-40 h-[420px] opacity-70"
        style={{
          background:
            "radial-gradient(60% 60% at 50% 30%, color-mix(in oklab, var(--c-accent) 22%, transparent), transparent 70%)",
        }}
      />
      <header className="relative flex items-center justify-between px-8 pt-6">
        <div className="flex items-center gap-2.5">
          <Logo size={28} />
          <span className="text-[14.5px] font-semibold text-fg">{t("app.name")}</span>
        </div>
        {step !== "done" && (
          <button
            type="button"
            onClick={() => void finish()}
            className="text-[12.5px] font-medium text-muted transition-colors hover:text-fg"
          >
            {t("wizard.skip")}
          </button>
        )}
      </header>

      <div className="relative mx-auto mt-6 flex w-full max-w-[560px] gap-1.5 px-8">
        {STEPS.map((s, idx) => (
          <div key={s} className="h-1 flex-1 overflow-hidden rounded-full bg-surface-3">
            <motion.div
              className="h-full rounded-full bg-accent"
              initial={false}
              animate={{ width: idx <= i ? "100%" : "0%" }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            />
          </div>
        ))}
      </div>
      <div className="relative mt-2 text-center text-[12px] text-subtle">
        {t("wizard.stepOf", { n: i + 1, total: STEPS.length })}
      </div>

      <div className="relative min-h-0 flex-1 overflow-y-auto">
        <AnimatePresence mode="wait" custom={dir} initial={false}>
          <motion.div
            key={step}
            custom={dir}
            initial={{ opacity: 0, x: dir * 28 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: dir * -20 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="mx-auto w-full max-w-[640px] px-8 py-8"
          >
            {step === "language" && <LanguageStep s={settings} set={updateSettings} onNext={() => go(1)} />}
            {step === "welcome" && <Welcome onStart={() => go(1)} />}
            {step === "mic" && <MicStep s={settings} set={updateSettings} />}
            {step === "model" && <ModelStep s={settings} set={updateSettings} setCanNext={setCanNext} picked={modelPicked} />}
            {step === "test" && <TestStep />}
            {step === "hotkeys" && <HotkeysStep s={settings} set={updateSettings} />}
            {step === "ai" && <AiStep s={settings} set={updateSettings} />}
            {step === "autostart" && <AutostartStep />}
            {step === "done" && <DoneStep s={settings} onFinish={() => void finish()} />}
          </motion.div>
        </AnimatePresence>
      </div>

      {step !== "language" && step !== "done" && (
        <footer className="relative flex items-center justify-between border-t border-line bg-surface/60 px-8 py-4 backdrop-blur">
          <Button variant="ghost" icon={<ArrowLeft className="size-4" />} onClick={() => go(-1)}>
            {t("wizard.back")}
          </Button>
          {/* у приветствия своя большая кнопка «Начать настройку» */}
          <div className={cn("flex items-center gap-2", step === "welcome" && "hidden")}>
            {!canNext && (
              <Button variant="ghost" onClick={() => go(1)}>
                {t("wizard.skipStep")}
              </Button>
            )}
            <Button
              variant="primary"
              iconRight={<ArrowRight className="size-4" />}
              disabled={!canNext}
              onClick={() => go(1)}
            >
              {t("wizard.next")}
            </Button>
          </div>
        </footer>
      )}
    </div>
  );
}

function StepHead({ icon, title, text }: { icon: ReactNode; title: TKey; text: TKey }) {
  return (
    <div className="mb-7 text-center">
      <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl border border-line bg-surface text-accent-text shadow-card [&>svg]:size-6">
        {icon}
      </div>
      <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-fg">{t(title)}</h2>
      <p className="mx-auto mt-2 max-w-md text-[13.5px] leading-relaxed text-muted">{t(text)}</p>
    </div>
  );
}

/**
 * Карточка шага. padded={false} — без внутреннего отступа: строки со своими px-5 и
 * разделителями во всю ширину (класс p-0 не помог бы — p-5 в CSS идёт позже и побеждает).
 */
function Panel({
  children,
  className,
  padded = true,
  ...rest
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
  "data-testid"?: string;
}) {
  return (
    <div className={cn("rounded-2xl border border-line bg-surface shadow-card", padded && "p-5", className)} {...rest}>
      {children}
    </div>
  );
}

// ——— 1. Язык ———

/**
 * Выбор языка — первым шагом: дальше всё на нём. Карточки подписаны на своём языке.
 * Язык Windows сохраняется как "system" (пойдёт за системой), другой — явным выбором.
 *
 * Язык интерфейса влияет и на распознавание: в режиме dictation_language="auto" приоритет
 * у него. Выбрали не язык Windows (русская Windows, английский интерфейс) — рядом «Язык
 * диктовки», чтобы это не случилось молча: можно закрепить язык, на котором говорите.
 */
function LanguageStep({ s, set, onNext }: StepProps & { onNext: () => void }) {
  const { state } = useCore();
  const current = getLocale();
  const sys = systemLocale(s.language, state?.ui_language);
  const dictLang: DictationLanguage = s.dictation_language ?? "auto";
  // Не прячем и после возврата к языку Windows, если язык диктовки уже закреплён
  const showDictation = current !== sys || dictLang !== "auto";
  const pick = (l: Locale) => {
    const pref = l === sys ? "system" : l;
    if (pref !== (s.language ?? "system")) void set({ language: pref });
  };
  return (
    <div className="pt-4 text-center">
      <StepHead icon={<Languages />} title="wizard.language.title" text="wizard.language.text" />
      <div role="radiogroup" className="grid grid-cols-2 gap-3 text-left">
        {LOCALES.map((l) => {
          const active = l === current;
          return (
            <button
              key={l}
              type="button"
              role="radio"
              aria-checked={active}
              lang={l}
              onClick={() => pick(l)}
              className={cn(
                "relative flex flex-col items-stretch rounded-2xl border bg-surface p-5 text-left transition-[border-color,box-shadow] duration-200",
                active ? "border-accent/60 shadow-glow" : "border-line shadow-card hover:border-line-strong",
              )}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="text-[18px] font-semibold tracking-[-0.01em] text-fg">{NATIVE_NAMES[l]}</span>
                <span
                  className={cn(
                    "flex size-5 shrink-0 items-center justify-center rounded-full border transition-colors",
                    active ? "border-accent bg-accent text-accent-fg" : "border-line-strong",
                  )}
                >
                  {active && <Check className="size-3" strokeWidth={3} />}
                </span>
              </span>
              <span className="mt-1 text-[13px] text-muted">{tIn(l, "wizard.language.sample")}</span>
              {l === sys && (
                <span className="mt-3 self-start" lang={current}>
                  <Badge icon={<Laptop />}>{t("wizard.language.windows")}</Badge>
                </span>
              )}
            </button>
          );
        })}
      </div>
      <AnimatePresence initial={false}>
        {showDictation && (
          <motion.div
            key="dictation"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-3 rounded-2xl border border-line bg-surface p-4 text-left shadow-card" data-testid="wizard-dictation-language">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <span className="text-[13.5px] font-medium text-fg">{t("settings.general.dictationLanguage")}</span>
                <Segmented<DictationLanguage>
                  size="sm"
                  value={dictLang}
                  onChange={(v) => void set({ dictation_language: v })}
                  options={[
                    { value: "auto", label: t("settings.general.dictationLanguageAuto"), icon: <Languages className="size-3.5" /> },
                    { value: "ru", label: NATIVE_NAMES.ru },
                    { value: "en", label: NATIVE_NAMES.en },
                  ]}
                />
              </div>
              <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
                {dictLang === "auto"
                  ? t("wizard.language.dictationHint", { lang: languageName(current) })
                  : t(`settings.general.dictationLanguageHints.${dictLang}`)}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <Button size="lg" variant="primary" className="mt-8" iconRight={<ArrowRight className="size-4" />} onClick={onNext}>
        {t("wizard.language.continue")}
      </Button>
    </div>
  );
}

// ——— 2. Приветствие ———

function Welcome({ onStart }: { onStart: () => void }) {
  const features: { icon: ReactNode; title: TKey; text: TKey }[] = [
    { icon: <Mic />, title: "wizard.welcome.f1", text: "wizard.welcome.f1Text" },
    { icon: <MonitorSmartphone />, title: "wizard.welcome.f2", text: "wizard.welcome.f2Text" },
    { icon: <ShieldCheck />, title: "wizard.welcome.f3", text: "wizard.welcome.f3Text" },
  ];
  return (
    <div className="pt-6 text-center">
      <motion.div
        initial={{ scale: 0.85, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", stiffness: 260, damping: 20 }}
        className="relative mx-auto mb-7 flex size-24 items-center justify-center"
      >
        {[0, 1].map((k) => (
          <motion.span
            key={k}
            className="absolute inset-0 rounded-[28px] border border-accent/40"
            animate={{ scale: [1, 1.45], opacity: [0.5, 0] }}
            transition={{ duration: 2.4, repeat: Infinity, delay: k * 1.2, ease: "easeOut" }}
          />
        ))}
        <Logo size={80} live className="rounded-[22px]" />
      </motion.div>
      <h1 className="text-[30px] font-semibold tracking-[-0.03em] text-fg">{t("wizard.welcome.title")}</h1>
      <p className="mx-auto mt-3 max-w-md text-[14.5px] leading-relaxed text-muted">{t("wizard.welcome.text")}</p>
      <div className="mt-8 grid gap-2.5 text-left">
        {features.map((f, idx) => (
          <motion.div
            key={f.title}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 + idx * 0.07, duration: 0.25 }}
            className="flex items-center gap-3.5 rounded-xl border border-line bg-surface px-4 py-3 shadow-card"
          >
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text [&>svg]:size-[18px]">
              {f.icon}
            </span>
            <div>
              <div className="text-[13.5px] font-semibold text-fg">{t(f.title)}</div>
              <div className="text-[12.5px] text-muted">{t(f.text)}</div>
            </div>
          </motion.div>
        ))}
      </div>
      <Button size="lg" variant="primary" className="mt-8" iconRight={<ArrowRight className="size-4" />} onClick={onStart}>
        {t("wizard.welcome.start")}
      </Button>
    </div>
  );
}

// ——— 3. Микрофон ———

interface StepProps {
  s: Settings;
  set: (p: SettingsPatch) => Promise<boolean>;
}

function MicStep({ s, set }: StepProps) {
  const devices = useLoad(() => call("list_devices"));
  useMicMonitor(true, s.input_device);

  const options: SelectOption<string | null>[] = [
    { value: null, label: t("settings.dictation.micDefault"), icon: <Mic /> },
    ...(devices.data ?? []).map((d) => ({
      value: d.name,
      label: d.name,
      hint: d.default ? t("settings.dictation.micSystem") : undefined,
    })),
  ];

  return (
    <div>
      <StepHead icon={<Mic />} title="wizard.mic.title" text="wizard.mic.text" />
      <Panel>
        <div className="flex items-center gap-2">
          <Select
            value={s.input_device}
            options={options}
            onChange={(v) => void set({ input_device: v })}
            className="flex-1"
          />
          <IconButton label={t("common.refresh")} onClick={devices.reload}>
            <RefreshCw className={cn("size-4", devices.loading && "animate-spin")} />
          </IconButton>
        </div>
        <div className="mt-6 rounded-xl bg-surface-2/70 px-4 py-5">
          <LiveWave active height={64} />
          <LevelBar active className="mt-4" />
        </div>
        <div className="mt-3 text-center text-[12.5px] text-subtle">{t("wizard.mic.hint")}</div>
      </Panel>
    </div>
  );
}

// ——— 4. CUDA и модель ———

interface Dl {
  pct: number;
  text: string;
  done: boolean;
  error: string | null;
  running: boolean;
}

function ModelStep({
  s,
  set,
  setCanNext,
  picked,
}: StepProps & { setCanNext: (v: boolean) => void; picked: MutableRefObject<boolean> }) {
  const toast = useToast();
  const { state } = useCore();
  const cuda = useLoad(() => cached("cuda_check", 10 * 60_000, () => call("cuda_check", undefined, { timeoutMs: 60_000 })));
  // Подбор по мощности компьютера: размеры моделей ядро спрашивает у Hugging Face (~5 с).
  // reason и note — на языке интерфейса: у каждого языка свой кэш (вернулись к шагу языка)
  const rec = useLoad(() =>
    cached(`model_recommend:${getLocale()}`, 10 * 60_000, () =>
      call("model_recommend", undefined, { timeoutMs: 30_000 }),
    ),
  );
  // model_ready — про settings.model в папке model_dir: сменились — перечитать
  const setup = useLoad(() => call("setup_status"), [s.model, s.model_dir]);
  const [dl, setDl] = useState<Record<DownloadWhat, Dl | null>>({ model: null, cuda: null });

  // Проверка CUDA в кэше на 10 минут — после загрузки библиотек и смены устройства
  // распознавания она устарела: сбрасываем и проверяем заново.
  const recheckCuda = () => {
    invalidate("cuda_check");
    cuda.reload();
  };

  useEvent("progress", (p: ProgressEvent) => {
    setDl((d) => ({ ...d, [p.what]: { pct: p.pct, text: p.text, done: p.done, error: p.error, running: !p.done && !p.error } }));
    if (p.done && !p.error) {
      setup.reload();
      if (p.what === "cuda") recheckCuda();
    }
  });

  // Ядро перезапустилось посреди загрузки — поток загрузки умер вместе с ним, события done
  // не будет. Сбрасываем «идёт загрузка», чтобы кнопка снова стала доступна (докачка .part).
  useEvent("hello", () => {
    setDl((d) => ({
      model: d.model?.running ? null : d.model,
      cuda: d.cuda?.running ? null : d.cuda,
    }));
  });

  const deviceKey = `${state?.device ?? ""}|${String(state?.model_loaded ?? "")}`;
  const lastDeviceKey = useRef(deviceKey);
  useEffect(() => {
    if (lastDeviceKey.current === deviceKey) return;
    lastDeviceKey.current = deviceKey;
    recheckCuda();
  }, [deviceKey]);

  const modelReady = Boolean(setup.data?.model_ready);
  useEffect(() => setCanNext(modelReady), [modelReady, setCanNext]);

  /** Модель из списка: устройство и точность — по рекомендации (их решает железо). */
  const choose = (model: string) => {
    picked.current = true;
    const r = rec.data?.recommended;
    const patch: SettingsPatch = { model };
    if (r) {
      patch.device = r.device;
      patch.compute_type = r.compute_type;
    }
    if (model === s.model && (patch.device ?? s.device) === s.device && (patch.compute_type ?? s.compute_type) === s.compute_type) {
      return;
    }
    // ошибка загрузки прежней модели к новой не относится
    setDl((d) => ({ ...d, model: d.model?.running ? d.model : null }));
    void set(patch);
  };

  // Рекомендацию подставляем сами один раз за проход мастера и только на первой установке:
  // мастер ещё не пройден, модели нет на диске и она не качается. Уже скачанную модель молча
  // не меняем; при повторном запуске мастера из настроек ядро уже качает или держит модель,
  // выбранную там, — подмена выбросила бы её загрузку. «Скачать» до прихода рекомендации
  // тоже закрепляет модель из настроек (start): ядро качает её, а не подставленную.
  useEffect(() => {
    if (picked.current || !rec.data || !setup.data) return;
    picked.current = true;
    if (!setup.data.model_ready && !setup.data.first_run_done && !dl.model?.running) {
      choose(rec.data.recommended.model);
    }
  }, [rec.data, setup.data]);

  // Сменилась папка — итог прошлого переноса или загрузки (ошибка, «Модель перенесена») к ней
  // не относится. Идущий не трогаем: удачный перенос меняет model_dir ещё до своего done
  useEffect(() => {
    setDl((d) => (d.model && !d.model.running ? { ...d, model: null } : d));
  }, [s.model_dir]);

  const start = async (what: DownloadWhat) => {
    if (what === "model") picked.current = true;
    setDl((d) => ({ ...d, [what]: { pct: 0, text: t("wizard.model.starting"), done: false, error: null, running: true } }));
    try {
      await call("setup_download", { what });
    } catch (e) {
      setDl((d) => ({ ...d, [what]: null }));
      toast({ tone: "error", title: t("wizard.model.downloadError"), description: errorText(e) });
    }
  };

  const c = cuda.data;
  const gpuOk = Boolean(c?.ok && c.device === "cuda");
  // Видеокарты NVIDIA нет — библиотеки CUDA (~1 ГБ) качать незачем.
  const noGpu = Boolean(c && !c.gpu_name && !cuda.loading);
  // Пока модель качается или переносится, ни модель, ни папку не меняем
  const modelBusy = Boolean(dl.model?.running);
  const size = rec.data?.options.find((o) => o.model === s.model)?.size_mb;

  return (
    <div>
      <StepHead icon={<Zap />} title="wizard.model.title" text="wizard.model.text" />
      <ModelChoice
        rec={rec.data}
        loading={rec.loading && !rec.data}
        error={rec.data ? null : rec.error}
        current={s.model}
        disabled={modelBusy}
        onChoose={choose}
      />
      <Panel className="mt-3">
        <div className="mb-3 flex items-start gap-3.5">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-surface-2 text-muted [&>svg]:size-5">
            <FolderDown />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] font-semibold text-fg">{t("wizard.model.folderTitle")}</div>
            <div className="text-[12.5px] text-muted">{t("wizard.model.folderText")}</div>
          </div>
        </div>
        <ModelFolder disabled={modelBusy} showDownloads={false} onChanged={setup.reload} />
      </Panel>
      <Panel padded={false} className="mt-3">
        <div className="flex items-center gap-3.5 border-b border-line px-5 py-4">
          <span
            className={cn(
              "flex size-10 shrink-0 items-center justify-center rounded-xl [&>svg]:size-5",
              cuda.loading ? "bg-surface-2 text-muted" : gpuOk ? "bg-success/12 text-success" : "bg-warn/14 text-warn",
            )}
          >
            {gpuOk || cuda.loading ? <Zap /> : <Cpu />}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] font-semibold text-fg">
              {cuda.loading ? t("wizard.model.checking") : gpuOk ? (c?.gpu_name ?? t("status.gpu")) : t("wizard.model.cpuOnly")}
            </div>
            <div className={cn("text-[12.5px]", cuda.error && !cuda.loading ? "text-danger" : "text-muted")}>
              {cuda.loading
                ? t("wizard.model.checkingText")
                : cuda.error
                  ? t("wizard.model.checkFailed", { error: cuda.error })
                  : gpuOk
                    ? t("wizard.model.gpuText", { vram: c?.vram_total_mb ? Math.round(c.vram_total_mb / 1024) : "?" })
                    : (c?.error ?? t("wizard.model.cpuText"))}
            </div>
          </div>
          {!cuda.loading && (cuda.error || !gpuOk) && (
            <IconButton label={t("wizard.model.recheck")} onClick={recheckCuda}>
              <RefreshCw className="size-4" />
            </IconButton>
          )}
          {cuda.loading ? <Spinner /> : <Badge tone={gpuOk ? "success" : "warn"}>{gpuOk ? "CUDA" : "CPU"}</Badge>}
        </div>

        <DownloadRow
          icon={<HardDrive />}
          title={t("wizard.model.cudaLibs")}
          text={noGpu && !setup.data?.cuda_ready ? t("wizard.model.cudaLibsNoGpu") : t("wizard.model.cudaLibsText")}
          ready={Boolean(setup.data?.cuda_ready)}
          loading={setup.loading && !setup.data}
          unavailable={noGpu && !dl.cuda ? t("wizard.model.notNeeded") : undefined}
          dl={dl.cuda}
          onStart={() => void start("cuda")}
        />
        <DownloadRow
          icon={<Download />}
          title={t("wizard.model.model", { model: s.model })}
          text={size ? t("wizard.model.modelText", { size: fmtMb(size) }) : t("wizard.model.modelTextNoSize")}
          ready={modelReady}
          loading={setup.loading && !setup.data}
          dl={dl.model}
          onStart={() => void start("model")}
        />
      </Panel>
      {setup.error && !setup.loading && (
        <div className="mt-3 flex items-center justify-center gap-2 text-[12.5px] text-danger">
          <CircleAlert className="size-3.5 shrink-0" />
          <span>{t("wizard.model.statusFailed", { error: setup.error })}</span>
          <Button size="sm" variant="ghost" icon={<RefreshCw className="size-4" />} onClick={setup.reload}>
            {t("common.retry")}
          </Button>
        </div>
      )}
      {!modelReady && setup.data && (
        <div className="mt-3 text-center text-[12.5px] text-subtle">{t("wizard.model.needModel")}</div>
      )}
    </div>
  );
}

function DownloadRow({
  icon,
  title,
  text,
  ready,
  loading,
  unavailable,
  dl,
  onStart,
}: {
  icon: ReactNode;
  title: string;
  text: string;
  ready: boolean;
  loading: boolean;
  /** Качать незачем (например, нет видеокарты NVIDIA) — вместо кнопки нейтральная метка. */
  unavailable?: string;
  dl: Dl | null;
  onStart: () => void;
}) {
  const running = Boolean(dl?.running);
  return (
    <div className="border-b border-line px-5 py-4 last:border-b-0">
      <div className="flex items-center gap-3.5">
        <span
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-xl [&>svg]:size-5",
            ready ? "bg-success/12 text-success" : "bg-surface-2 text-muted",
          )}
        >
          {ready ? <Check /> : icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold text-fg">{title}</div>
          <div className="text-[12.5px] text-muted">{text}</div>
        </div>
        {loading ? (
          <Spinner />
        ) : ready ? (
          <Badge tone="success" icon={<Check />}>
            {t("wizard.model.ready")}
          </Badge>
        ) : unavailable ? (
          <Badge>{unavailable}</Badge>
        ) : (
          <Button size="sm" variant="primary" icon={<Download className="size-4" />} loading={running} onClick={onStart}>
            {dl?.error ? t("common.retry") : t("wizard.model.download")}
          </Button>
        )}
      </div>
      <AnimatePresence initial={false}>
        {dl && !ready && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="pt-3.5">
              <ProgressBar value={dl.pct} tone={dl.error ? "danger" : "accent"} />
              <div className={cn("mt-1.5 flex justify-between text-[12px]", dl.error ? "text-danger" : "text-subtle")}>
                <span className="truncate">{dl.error ?? dl.text}</span>
                <span className="tabular">{dl.pct}%</span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/**
 * Рекомендация под этот компьютер (model_recommend) и выбор модели. Подбор не удался — мастер
 * работает дальше с моделью из настроек: показываем её и причину.
 */
function ModelChoice({
  rec,
  loading,
  error,
  current,
  disabled,
  onChoose,
}: {
  rec: ModelRecommend | undefined;
  loading: boolean;
  error: string | null;
  current: string;
  disabled: boolean;
  onChoose: (model: string) => void;
}) {
  const hardware = rec
    ? [tp("units.threads", rec.cpu_threads), t("wizard.model.ram", { n: fmtDecimal(rec.ram_gb, 0) })].join(" · ")
    : null;
  return (
    <Panel padded={false} data-testid="wizard-model-choice">
      <div className="flex items-start gap-3.5 px-5 py-4">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-text [&>svg]:size-5">
          <Gauge />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold text-fg">
            {loading
              ? t("wizard.model.recommendLoading")
              : rec
                ? t("wizard.model.recommend", { model: rec.recommended.model })
                : t("wizard.model.currentModel", { model: current })}
          </div>
          {rec ? (
            <>
              <div className="text-[12.5px] text-muted">{rec.reason}</div>
              {hardware && <div className="mt-0.5 text-[12px] text-subtle">{hardware}</div>}
            </>
          ) : error && !loading ? (
            <div className="text-[12.5px] text-danger">{t("wizard.model.recommendFailed", { error })}</div>
          ) : null}
        </div>
        {loading && <Spinner />}
      </div>
      {rec && rec.options.length > 0 && (
        <div role="radiogroup" aria-label={t("wizard.model.chooseTitle")} className="space-y-1 border-t border-line p-2">
          {rec.options.map((o) => (
            <ModelOptionRow key={o.model} o={o} active={o.model === current} disabled={disabled} onChoose={onChoose} />
          ))}
        </div>
      )}
    </Panel>
  );
}

function ModelOptionRow({
  o,
  active,
  disabled,
  onChoose,
}: {
  o: ModelOption;
  active: boolean;
  disabled: boolean;
  onChoose: (model: string) => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      aria-label={`${o.model}: ${o.note}`}
      disabled={disabled}
      onClick={() => onChoose(o.model)}
      className={cn(
        "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors disabled:opacity-60",
        active ? "bg-accent-soft" : "hover:bg-surface-2",
      )}
    >
      <span
        className={cn(
          "flex size-4 shrink-0 items-center justify-center rounded-full border-2",
          active ? "border-accent" : "border-line-strong",
        )}
      >
        {active && <motion.span layoutId="wizard-model-radio" className="size-1.5 rounded-full bg-accent" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="font-mono text-[13px] font-semibold text-fg">{o.model}</span>
          {o.recommended && <Badge tone="accent">{t("wizard.model.recommendedBadge")}</Badge>}
        </span>
        <span className="block truncate text-[12px] text-muted" title={o.note}>
          {o.note}
        </span>
      </span>
      <Rating label={t("wizard.model.quality")} n={o.quality} />
      <Rating label={t("wizard.model.speed")} n={o.speed} />
      <span className="tabular w-14 shrink-0 text-right text-[12.5px] text-muted">{fmtMb(o.size_mb)}</span>
    </button>
  );
}

/** Оценка 1–5 полосками (качество, скорость). */
function Rating({ label, n }: { label: string; n: ModelRating }) {
  const text = t("wizard.model.rating", { label, n });
  return (
    <span className="flex shrink-0 flex-col items-end gap-1" title={text} aria-label={text} role="img">
      <span className="text-[10.5px] leading-none text-subtle">{label}</span>
      <span className="flex gap-0.5">
        {[1, 2, 3, 4, 5].map((k) => (
          <span key={k} className={cn("h-1.5 w-2.5 rounded-full", k <= n ? "bg-accent" : "bg-surface-3")} />
        ))}
      </span>
    </span>
  );
}

// ——— 5. Тест распознавания ———

function TestStep() {
  const { state } = useCore();
  const toast = useToast();
  const [rec, setRec] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<TestRecordResult | null>(null);
  const ready = state?.model_loaded && state.state !== "loading";

  const recRef = useRef(false);
  recRef.current = rec;
  useEffect(
    () => () => {
      // ушли со шага во время записи — остановить
      if (recRef.current) call("test_record_stop").catch(() => {});
    },
    [],
  );

  const toggle = async () => {
    if (!rec) {
      setRes(null);
      try {
        await call("test_record_start");
        setRec(true);
      } catch (e) {
        toast({ tone: "error", title: t("wizard.test.error"), description: errorText(e) });
      }
      return;
    }
    setRec(false);
    setBusy(true);
    try {
      setRes(await call("test_record_stop", undefined, { timeoutMs: 60_000 }));
    } catch (e) {
      toast({ tone: "error", title: t("wizard.test.error"), description: errorText(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <StepHead icon={<Sparkles />} title="wizard.test.title" text="wizard.test.text" />
      <Panel className="flex flex-col items-center py-8">
        <div className="relative flex size-28 items-center justify-center">
          <AnimatePresence>
            {rec &&
              [0, 1, 2].map((k) => (
                <motion.span
                  key={k}
                  className="absolute inset-0 rounded-full bg-danger/20"
                  initial={{ scale: 0.8, opacity: 0.6 }}
                  animate={{ scale: 1.6, opacity: 0 }}
                  exit={{ opacity: 0, transition: { duration: 0.2 } }}
                  transition={{ duration: 1.8, repeat: Infinity, delay: k * 0.6, ease: "easeOut" }}
                />
              ))}
          </AnimatePresence>
          <motion.button
            type="button"
            aria-label={rec ? t("wizard.test.stopLabel") : t("wizard.test.startLabel")}
            aria-pressed={rec}
            disabled={!ready || busy}
            onClick={() => void toggle()}
            whileHover={{ scale: 1.04 }}
            whileTap={{ scale: 0.95 }}
            className={cn(
              "relative flex size-20 items-center justify-center rounded-full text-white shadow-pop transition-colors duration-200 disabled:opacity-50",
              rec ? "bg-danger" : "bg-accent",
            )}
          >
            {busy ? <Spinner className="size-7 text-white" /> : rec ? <Square className="size-7 fill-current" /> : <Mic className="size-8" />}
          </motion.button>
        </div>
        <div className="mt-4 text-[13.5px] font-medium text-fg">
          {!ready ? t("wizard.test.waitModel") : busy ? t("wizard.test.recognizing") : rec ? t("wizard.test.stop") : t("wizard.test.start")}
        </div>
        <div className="mt-5 w-full max-w-sm">
          <LiveWave active={rec} height={48} />
        </div>
        <div className="mt-2 text-[12.5px] text-subtle">{t("wizard.test.phrase")}</div>
      </Panel>
      <AnimatePresence>
        {res && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.22 }}
          >
            <Panel className="mt-3">
              <div className="mb-2 flex items-center gap-2 text-[12.5px] font-medium text-success">
                <Check className="size-4" />
                {t("wizard.test.recognized")}
              </div>
              <div className="text-[15px] leading-relaxed text-fg selectable">
                {res.text || <span className="text-subtle">{t("wizard.test.empty")}</span>}
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <Badge icon={<Timer />}>{t("wizard.test.audio", { v: fmtSeconds(res.audio_s) })}</Badge>
                <Badge icon={<Zap />} tone="success">
                  {t("wizard.test.asr", { v: fmtMs(res.asr_ms) })}
                </Badge>
                <Badge icon={<Languages />}>{res.language.toUpperCase()}</Badge>
              </div>
            </Panel>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ——— 6. Хоткеи ———

function HotkeysStep({ s, set }: StepProps) {
  const rows: { k: "ptt_key" | "broadcast_modifier" | "command_modifier" | "cancel_key"; title: TKey; hint: TKey }[] = [
    { k: "ptt_key", title: "settings.dictation.ptt", hint: "wizard.hotkeys.ptt" },
    { k: "broadcast_modifier", title: "settings.dictation.broadcast", hint: "wizard.hotkeys.broadcast" },
    { k: "command_modifier", title: "settings.dictation.command", hint: "wizard.hotkeys.command" },
    { k: "cancel_key", title: "settings.dictation.cancel", hint: "wizard.hotkeys.cancel" },
  ];
  return (
    <div>
      <StepHead icon={<Keyboard />} title="wizard.hotkeys.title" text="wizard.hotkeys.text" />
      <Panel padded={false}>
        {rows.map((r) => (
          <div key={r.k} className="flex items-center gap-4 border-b border-line px-5 py-3.5 last:border-b-0">
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium text-fg">{t(r.title)}</div>
              <div className="text-[12.5px] text-muted">{t(r.hint)}</div>
            </div>
            <HotkeyCapture value={s[r.k]} combo={r.k === "ptt_key"} onChange={(v) => void set({ [r.k]: v } as SettingsPatch)} />
          </div>
        ))}
      </Panel>
      <div className="mt-4 flex items-center justify-center gap-2 text-[12.5px] text-muted">
        {t("wizard.hotkeys.handsFree")}
        <KeyCombo keys={[s.ptt_key]} />
        <span className="font-medium text-subtle">×2</span>
      </div>
    </div>
  );
}

// ——— 7. ИИ ———

function AiStep({ s, set }: StepProps) {
  return (
    <div>
      <StepHead icon={<Sparkles />} title="wizard.ai.title" text="wizard.ai.text" />
      <Panel>
        <KeyManager provider="openrouter" compact />
      </Panel>
      <Panel className="mt-3 flex items-center gap-4">
        <div className="flex-1">
          <div className="text-[13.5px] font-semibold text-fg">{t("wizard.ai.enable")}</div>
          <div className="text-[12.5px] text-muted">{t("wizard.ai.enableHint")}</div>
        </div>
        <Switch label={t("wizard.ai.enable")} checked={s.ai_enabled} onChange={(v) => void set({ ai_enabled: v })} />
      </Panel>
    </div>
  );
}

// ——— 8. Автозапуск ———

function AutostartStep() {
  const toast = useToast();
  const [on, setOn] = useState<boolean | null>(null);
  const tauri = inTauri();
  useEffect(() => {
    void autostartEnabled().then(setOn);
  }, []);
  return (
    <div>
      <StepHead icon={<Power />} title="wizard.autostart.title" text="wizard.autostart.text" />
      <Panel className="flex items-center gap-4">
        <span className="flex size-10 items-center justify-center rounded-xl bg-accent-soft text-accent-text">
          <Power className="size-5" />
        </span>
        <div className="flex-1">
          <div className="text-[13.5px] font-semibold text-fg">{t("wizard.autostart.switch")}</div>
          <div className="text-[12.5px] text-muted">
            {tauri ? t("wizard.autostart.hint") : t("settings.general.onlyInApp")}
          </div>
        </div>
        <Switch
          label={t("wizard.autostart.switch")}
          checked={Boolean(on)}
          disabled={!tauri || on === null}
          onChange={async (v) => {
            try {
              setOn(await setAutostart(v));
            } catch (e) {
              toast({ tone: "error", title: t("errors.autostart"), description: errorText(e) });
            }
          }}
        />
      </Panel>
    </div>
  );
}

// ——— 9. Готово ———

function DoneStep({ s, onFinish }: { s: Settings; onFinish: () => void }) {
  return (
    <div className="pt-6 text-center">
      <div className="relative mx-auto mb-7 flex size-24 items-center justify-center">
        {Array.from({ length: 10 }, (_, k) => {
          const a = (k / 10) * Math.PI * 2;
          return (
            <motion.span
              key={k}
              className="absolute size-1.5 rounded-full bg-accent"
              initial={{ x: 0, y: 0, opacity: 0 }}
              animate={{ x: Math.cos(a) * 64, y: Math.sin(a) * 64, opacity: [0, 1, 0] }}
              transition={{ duration: 1.1, delay: 0.25, ease: "easeOut" }}
            />
          );
        })}
        <motion.div
          initial={{ scale: 0.6, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 300, damping: 18 }}
          className="flex size-20 items-center justify-center rounded-full bg-success text-white shadow-pop"
        >
          <svg viewBox="0 0 24 24" className="size-10">
            <motion.path
              d="M5 12.5l4.5 4.5L19 7.5"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.6}
              strokeLinecap="round"
              strokeLinejoin="round"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.4, delay: 0.2 }}
            />
          </svg>
        </motion.div>
      </div>
      <h1 className="text-[28px] font-semibold tracking-[-0.03em] text-fg">{t("wizard.done.title")}</h1>
      <p className="mx-auto mt-3 max-w-md text-[14px] leading-relaxed text-muted">{t("wizard.done.text")}</p>
      <div className="mx-auto mt-7 flex max-w-sm items-center justify-between rounded-xl border border-line bg-surface px-4 py-3 shadow-card">
        <span className="text-[13px] text-muted">{t("wizard.done.hold")}</span>
        <KeyCombo keys={[s.ptt_key]} />
      </div>
      <div className="mx-auto mt-2 flex max-w-sm items-center justify-between rounded-xl border border-line bg-surface px-4 py-3 shadow-card">
        <span className="text-[13px] text-muted">{t("wizard.done.pill")}</span>
        <span className="text-[12.5px] font-medium text-fg">{t("wizard.done.cancel", { key: keyLabel(s.cancel_key) })}</span>
      </div>
      <Button size="lg" variant="primary" className="mt-8" iconRight={<ArrowRight className="size-4" />} onClick={onFinish}>
        {t("wizard.done.open")}
      </Button>
      {!s.ai_enabled && (
        <div className="mt-4 flex items-center justify-center gap-1.5 text-[12.5px] text-subtle">
          <CircleAlert className="size-3.5" />
          {t("wizard.done.aiOff")}
        </div>
      )}
    </div>
  );
}
