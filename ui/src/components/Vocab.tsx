// «Словарь → Частые слова»: подсказка распознаванию из вашей истории диктовок (vocab_list)
// и текста рядом с курсором. Переключатели vocab_enabled / context_enabled, список слов
// с частотой, любое слово можно исключить (vocab_exclude).
import { AnimatePresence, motion } from "framer-motion";
import { AppWindow, ChevronDown, Lightbulb, ScanText, ShieldCheck, Sigma, TextCursorInput } from "lucide-react";
import { useMemo, useState } from "react";
import { t, tp, useLocale } from "../i18n";
import { cn } from "../lib/cn";
import { appName } from "../lib/format";
import { useDebounced, useEvent, useLoad } from "../lib/hooks";
import { errorText } from "../lib/hub";
import { useCore } from "../lib/store";
import type { VocabItem } from "../lib/types";
import { call } from "../lib/ws";
import { AppIcon } from "./AppIcon";
import { Button, Switch } from "./ui/controls";
import { Card, EmptyState, LoadError, SectionTitle, SettingRow, Skeleton } from "./ui/display";
import { Select, type SelectOption } from "./ui/select";
import { useToast } from "./ui/toast";

const STEP = 50;
const MAX = 200;
const ALL = "";

export function VocabPanel() {
  const { settings, updateSettings } = useCore();
  const toast = useToast();
  const [process, setProcess] = useState<string>(ALL);
  const [limit, setLimit] = useState(STEP);
  const list = useLoad(() => call("vocab_list", { ...(process ? { process } : {}), limit }), [process, limit]);
  const recent = useLoad(() => call("recent_apps"));
  // Новая диктовка — частоты пересчитаны ядром: перечитать (не чаще раза в 1,5 с)
  const refresh = useDebounced(() => list.reload(), 1500);
  useEvent("history", () => refresh.call());

  const vocabOn = settings?.vocab_enabled ?? true;
  const contextOn = settings?.context_enabled ?? true;

  const toggle = async (item: VocabItem, excluded: boolean) => {
    list.setData((xs) => (xs ?? []).map((x) => (x.word === item.word ? { ...x, excluded } : x)));
    try {
      await call("vocab_exclude", { word: item.word, excluded });
    } catch (e) {
      list.reload();
      toast({ tone: "error", title: t("errors.save"), description: errorText(e) });
    }
  };

  const locale = useLocale();
  const processOptions = useMemo<SelectOption<string>[]>(() => {
    const opts: SelectOption<string>[] = [{ value: ALL, label: t("vocab.allApps"), icon: <AppWindow /> }];
    const seen = new Set<string>();
    for (const a of recent.data ?? []) {
      const p = a.process.toLowerCase();
      if (seen.has(p)) continue;
      seen.add(p);
      opts.push({ value: p, label: appName(p), hint: p, icon: <AppIcon process={p} size={18} /> });
    }
    if (process && !seen.has(process)) opts.push({ value: process, label: appName(process), hint: process });
    return opts;
  }, [recent.data, process, locale]);

  const items = list.data ?? [];
  const top = Math.max(1, ...items.map((x) => x.count));
  const used = items.filter((x) => !x.excluded).length;

  return (
    <div className="space-y-8">
      <Card padded={false} className="overflow-hidden" data-testid="vocab-hints">
        <div className="flex gap-3.5 px-5 pb-4 pt-[18px]">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-text">
            <Lightbulb className="size-[18px]" />
          </div>
          <div className="min-w-0">
            <div className="text-[14px] font-semibold text-fg">{t("vocab.hintsTitle")}</div>
            <p className="mt-0.5 max-w-2xl text-[12.5px] leading-relaxed text-muted">{t("vocab.hintsText")}</p>
          </div>
        </div>
        <SettingRow
          className="border-t"
          title={
            <span className="flex items-center gap-2">
              <Sigma className="size-4 text-subtle" />
              {t("vocab.useVocab")}
            </span>
          }
          description={t("vocab.useVocabHint")}
        >
          <Switch label={t("vocab.useVocab")} checked={vocabOn} onChange={(v) => void updateSettings({ vocab_enabled: v })} />
        </SettingRow>
        <SettingRow
          title={
            <span className="flex items-center gap-2">
              <TextCursorInput className="size-4 text-subtle" />
              {t("vocab.useContext")}
            </span>
          }
          description={t("vocab.useContextHint")}
        >
          <Switch label={t("vocab.useContext")} checked={contextOn} onChange={(v) => void updateSettings({ context_enabled: v })} />
        </SettingRow>
        <div className="flex items-start gap-2 border-t border-line bg-surface-2/40 px-5 py-3 text-[12px] leading-relaxed text-subtle">
          <ShieldCheck className="mt-[2px] size-3.5 shrink-0" />
          <span>{t("vocab.privacy")}</span>
        </div>
      </Card>

      <section data-testid="vocab-list">
        <SectionTitle
          hint={t("vocab.listHint")}
          right={
            <div className="flex items-center gap-3">
              {list.data && items.length > 0 && (
                <span className="whitespace-nowrap text-[12px] text-subtle tabular">{t("vocab.counter", { used, total: items.length })}</span>
              )}
              <Select value={process} options={processOptions} onChange={setProcess} size="sm" className="w-[220px]" minWidth={260} align="right" />
            </div>
          }
        >
          {t("vocab.listTitle")}
        </SectionTitle>

        <AnimatePresence initial={false}>
          {!vocabOn && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="mb-3 flex items-center gap-2.5 rounded-xl border border-warn/30 bg-warn/8 px-4 py-2.5 text-[12.5px] text-warn">
                <ScanText className="size-4 shrink-0" />
                <span className="flex-1">{t("vocab.offNote")}</span>
                <Button size="sm" variant="secondary" onClick={() => void updateSettings({ vocab_enabled: true })}>
                  {t("vocab.turnOn")}
                </Button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {list.loading && !list.data ? (
          <Card padded={false} className="grid grid-cols-2">
            {Array.from({ length: 8 }, (_, i) => (
              <div key={i} className={cn("flex items-center gap-3 border-b border-line px-5 py-3", i % 2 === 1 && "border-l")}>
                <Skeleton className="h-4 w-28" />
                <Skeleton className="ml-auto h-2 w-20" />
                <Skeleton className="h-5 w-9" />
              </div>
            ))}
          </Card>
        ) : list.error && !list.data ? (
          <Card>
            <LoadError compact error={list.error} onRetry={list.reload} />
          </Card>
        ) : items.length === 0 ? (
          <Card>
            <EmptyState
              compact
              icon={<Sigma />}
              title={process ? t("vocab.emptyApp.title") : t("vocab.empty.title")}
              text={process ? t("vocab.emptyApp.text", { app: appName(process) }) : t("vocab.empty.text")}
            />
          </Card>
        ) : (
          <>
            <Card padded={false} className={cn("grid grid-cols-2 overflow-hidden transition-opacity", !vocabOn && "opacity-60")}>
              {items.map((w, i) => (
                <WordRow key={w.word} item={w} top={top} right={i % 2 === 1} onToggle={(ex) => void toggle(w, ex)} />
              ))}
              {items.length % 2 === 1 && <div className="border-l border-line" />}
            </Card>
            {items.length >= limit && limit < MAX && (
              <div className="mt-3 flex justify-center">
                <Button size="sm" variant="ghost" icon={<ChevronDown className="size-4" />} onClick={() => setLimit((l) => l + STEP)}>
                  {t("vocab.more")}
                </Button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function WordRow({
  item,
  top,
  right,
  onToggle,
}: {
  item: VocabItem;
  top: number;
  right: boolean;
  onToggle: (excluded: boolean) => void;
}) {
  return (
    <div
      className={cn(
        "-mb-px flex items-center gap-3 border-b border-line px-5 py-2.5 transition-colors hover:bg-surface-2/50",
        right && "border-l",
      )}
    >
      <span
        className={cn(
          "min-w-0 flex-1 truncate text-[13.5px] font-medium selectable",
          item.excluded ? "text-subtle line-through decoration-subtle/60" : "text-fg",
        )}
        title={item.word}
      >
        {item.word}
      </span>
      <span className="flex w-[108px] shrink-0 items-center gap-2" title={tp("vocab.times", item.count)}>
        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
          <motion.span
            className={cn("block h-full rounded-full", item.excluded ? "bg-subtle/50" : "bg-accent")}
            initial={{ width: 0 }}
            animate={{ width: `${Math.max(6, Math.round((item.count / top) * 100))}%` }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
          />
        </span>
        <span className="w-9 text-right text-[12px] text-subtle tabular">{item.count}</span>
      </span>
      <Switch
        size="sm"
        label={item.excluded ? t("vocab.include", { word: item.word }) : t("vocab.exclude", { word: item.word })}
        checked={!item.excluded}
        onChange={(on) => onToggle(!on)}
      />
    </div>
  );
}
