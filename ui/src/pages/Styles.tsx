import { AnimatePresence, motion } from "framer-motion";
import {
  Briefcase,
  Check,
  CircleAlert,
  CodeXml,
  Coins,
  FlaskConical,
  Hourglass,
  MessageCircle,
  Server,
  Sparkles,
  Timer,
  Type,
  WandSparkles,
  Zap,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button, Textarea } from "../components/ui/controls";
import { Badge, Card, LoadError, PageHeader, SectionTitle, Skeleton } from "../components/ui/display";
import { Select } from "../components/ui/select";
import { t, tDyn } from "../i18n";
import { cn } from "../lib/cn";
import { fmtCost, fmtMs } from "../lib/format";
import { errorText } from "../lib/hub";
import { navigate } from "../lib/router";
import { useCore } from "../lib/store";
import type { AiMode, AiTestResult } from "../lib/types";
import { call } from "../lib/ws";

export const STYLE_ICONS: Record<string, ReactNode> = {
  as_is: <Type />,
  normal: <Sparkles />,
  business: <Briefcase />,
  messenger: <MessageCircle />,
  code: <CodeXml />,
};

export function StylesPage() {
  const { settings, styles, stylesError, reloadStyles, updateSettings } = useCore();
  if (!settings) return null;
  const current = settings.default_style;

  return (
    <div>
      <PageHeader title={t("styles.title")} subtitle={t("styles.subtitle")} />

      <AnimatePresence initial={false}>
        {!settings.ai_enabled && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="mb-5 flex items-center gap-3 rounded-xl border border-accent/25 bg-accent-soft px-4 py-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-fg">
                <WandSparkles className="size-4" />
              </span>
              <div className="flex-1">
                <div className="text-[13.5px] font-medium text-fg">{t("styles.aiOff.title")}</div>
                <div className="text-[12.5px] text-muted">{t("styles.aiOff.text")}</div>
              </div>
              <Button size="sm" variant="primary" onClick={() => navigate("settings/ai")}>
                {t("styles.aiOff.action")}
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <SectionTitle hint={t("styles.defaultHint")}>{t("styles.defaultTitle")}</SectionTitle>
      {styles.length === 0 && stylesError && (
        <Card className="mb-3">
          <LoadError compact error={stylesError} onRetry={reloadStyles} />
        </Card>
      )}
      <div className="grid grid-cols-2 gap-3 @min-[50rem]:grid-cols-3">
        {styles.length === 0
          ? (stylesError ? [] : [0, 1, 2, 3, 4]).map((i) => <Skeleton key={i} className="h-[150px] rounded-2xl" />)
          : styles.map((s, i) => {
              const active = s.id === current;
              return (
                <motion.button
                  key={s.id}
                  type="button"
                  onClick={() => void updateSettings({ default_style: s.id })}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.22, delay: i * 0.035 }}
                  whileHover={{ y: -2 }}
                  whileTap={{ scale: 0.985 }}
                  className={cn(
                    "relative flex flex-col rounded-2xl border p-4 text-left transition-[border-color,box-shadow,background-color] duration-200",
                    active
                      ? "border-accent/60 bg-surface shadow-glow"
                      : "border-line bg-surface shadow-card hover:border-line-strong hover:shadow-pop",
                  )}
                >
                  <div className="flex items-start justify-between">
                    <span
                      className={cn(
                        "flex size-9 items-center justify-center rounded-xl [&>svg]:size-[18px]",
                        active ? "bg-accent text-accent-fg" : "bg-surface-2 text-muted",
                      )}
                    >
                      {STYLE_ICONS[s.id] ?? <Sparkles />}
                    </span>
                    <AnimatePresence>
                      {active && (
                        <motion.span
                          initial={{ opacity: 0, scale: 0.8 }}
                          animate={{ opacity: 1, scale: 1 }}
                          exit={{ opacity: 0, scale: 0.8 }}
                        >
                          <Badge tone="accent" icon={<Check />}>
                            {t("styles.isDefault")}
                          </Badge>
                        </motion.span>
                      )}
                    </AnimatePresence>
                  </div>
                  <div className="mt-3 text-[14px] font-semibold text-fg">{s.name}</div>
                  <div className="mt-1 flex-1 text-[12.5px] leading-relaxed text-muted">{s.description}</div>
                  <div className="mt-3 rounded-lg bg-surface-2 px-2.5 py-2 text-[12px] leading-snug text-muted italic">
                    {tDyn(`styles.examples.${s.id}`, "")}
                  </div>
                </motion.button>
              );
            })}
      </div>

      <SectionTitle className="mt-9" hint={t("styles.mode.hint")}>
        {t("styles.mode.title")}
      </SectionTitle>
      <AiModePicker value={settings.ai_mode} onChange={(v) => void updateSettings({ ai_mode: v })} />

      <SectionTitle className="mt-9" hint={t("styles.sandbox.hint")}>
        {t("styles.sandbox.title")}
      </SectionTitle>
      <Sandbox />
    </div>
  );
}

export function AiModePicker({ value, onChange }: { value: AiMode; onChange: (v: AiMode) => void }) {
  const opts: { v: AiMode; icon: ReactNode; title: string; text: string }[] = [
    { v: "wait", icon: <Hourglass />, title: t("styles.mode.wait"), text: t("styles.mode.waitText") },
    { v: "raw_first", icon: <Zap />, title: t("styles.mode.rawFirst"), text: t("styles.mode.rawFirstText") },
  ];
  return (
    <div className="grid grid-cols-2 gap-3">
      {opts.map((o) => {
        const active = o.v === value;
        return (
          <button
            key={o.v}
            type="button"
            onClick={() => onChange(o.v)}
            className={cn(
              "flex items-start gap-3 rounded-2xl border p-4 text-left transition-[border-color,box-shadow] duration-200",
              active ? "border-accent/60 bg-surface shadow-glow" : "border-line bg-surface shadow-card hover:border-line-strong",
            )}
          >
            <span
              className={cn(
                "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                active ? "border-accent" : "border-line-strong",
              )}
            >
              {active && <motion.span layoutId="ai-mode-dot" className="size-2 rounded-full bg-accent" />}
            </span>
            <span className="min-w-0">
              <span className="flex items-center gap-2 text-[14px] font-semibold text-fg [&>svg]:size-4 [&>svg]:text-subtle">
                {o.icon}
                {o.title}
              </span>
              <span className="mt-1 block text-[12.5px] leading-relaxed text-muted">{o.text}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Sandbox() {
  const { settings, styles } = useCore();
  const [text, setText] = useState("");
  const [style, setStyle] = useState<string>(settings?.default_style ?? "normal");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AiTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await call("ai_test", { text, style }, { timeoutMs: 60_000 });
      setResult(r);
    } catch (e) {
      setResult(null);
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card padded={false} className="overflow-hidden">
      <div className="p-5">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[12.5px] font-medium text-muted">{t("styles.sandbox.input")}</span>
          <button
            type="button"
            onClick={() => setText(t("styles.sandbox.sample"))}
            className="text-[12.5px] font-medium text-accent-text hover:underline"
          >
            {t("styles.sandbox.useSample")}
          </button>
        </div>
        <Textarea
          rows={4}
          value={text}
          placeholder={t("styles.sandbox.placeholder")}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.ctrlKey) {
              e.preventDefault();
              void run();
            }
          }}
        />
        <div className="mt-3 flex items-center gap-2">
          <Select
            value={style}
            onChange={setStyle}
            options={styles.map((s) => ({ value: s.id, label: s.name, icon: STYLE_ICONS[s.id] }))}
            className="w-[240px]"
          />
          <Button
            variant="primary"
            icon={<FlaskConical className="size-4" />}
            loading={busy}
            disabled={!text.trim()}
            onClick={() => void run()}
          >
            {t("styles.sandbox.run")}
          </Button>
          <span className="ml-auto text-[12px] text-subtle">{t("styles.sandbox.shortcut")}</span>
        </div>
      </div>
      <AnimatePresence initial={false}>
        {(busy || result || error) && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden border-t border-line bg-surface-2/50"
          >
            <div className="p-5">
              <div className="mb-2 text-[12.5px] font-medium text-muted">{t("styles.sandbox.output")}</div>
              {busy ? (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-4/5" />
                </div>
              ) : error ? (
                <div className="flex items-start gap-2 text-[13.5px] text-danger">
                  <CircleAlert className="mt-0.5 size-4 shrink-0" />
                  {error}
                </div>
              ) : (
                result && (
                  <>
                    <div className="whitespace-pre-wrap text-[14px] leading-relaxed text-fg selectable">{result.text}</div>
                    <div className="mt-4 flex flex-wrap gap-1.5">
                      <Badge icon={<Timer />}>{fmtMs(result.ms)}</Badge>
                      <Badge icon={<Coins />}>
                        {result.cost_usd === null ? t("styles.sandbox.costUnknown") : fmtCost(result.cost_usd)}
                      </Badge>
                      <Badge icon={<Server />}>{result.provider}</Badge>
                      <Badge>{result.model}</Badge>
                    </div>
                  </>
                )
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}
