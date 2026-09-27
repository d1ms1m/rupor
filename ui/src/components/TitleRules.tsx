// «Правила по названию окна» (title_rules): стиль и способ вставки для окна, в заголовке
// которого есть подстрока, — сервер в RDP, вкладка браузера, конкретный чат. Важнее правил
// приложений; при нескольких совпадениях действует правило с самым длинным title.
import { AnimatePresence, motion } from "framer-motion";
import { AppWindow, Globe, Monitor, Plus, RefreshCw, Trash, TextSearch } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { intlTag, t, useLocale } from "../i18n";
import { cn } from "../lib/cn";
import { appName, foldTitle, titleRuleKey } from "../lib/format";
import { useLoad } from "../lib/hooks";
import { errorText } from "../lib/hub";
import { reloadRdp, useRdpWindows } from "../lib/rdp";
import { useCore } from "../lib/store";
import type { InsertMode, RecentApp, TitleRule } from "../lib/types";
import { call } from "../lib/ws";
import { STYLE_ICONS } from "../pages/Styles";
import { AppIcon } from "./AppIcon";
import { Button, IconButton, Input } from "./ui/controls";
import { Card, EmptyState, LoadError, SectionTitle, Skeleton, Spinner } from "./ui/display";
import { Modal } from "./ui/overlay";
import { Select, type SelectOption } from "./ui/select";
import { useToast } from "./ui/toast";

export const ANY_PROCESS = "*";
const MIN_TITLE = 2;
const OTHER = "\u0000other";

// Ключ правила — как у ядра (регистр и «ё»/«е» не различаются), иначе «Ёлка» и «Елка» здесь —
// два правила, а в ядре второе молча заменяет первое.
const ruleKey = titleRuleKey;

function sortRules(a: TitleRule, b: TitleRule): number {
  if (a.process === ANY_PROCESS && b.process !== ANY_PROCESS) return 1;
  if (b.process === ANY_PROCESS && a.process !== ANY_PROCESS) return -1;
  return a.process.localeCompare(b.process) || a.title.localeCompare(b.title, intlTag());
}

/** Части заголовка «Задача ANL-482 — Jira — Google Chrome» → ["Задача ANL-482", "Jira", "Google Chrome"]. */
export function titleParts(title: string): string[] {
  const parts = title
    .split(/\s+[—–\-|·•:]\s+/)
    .map((p) => p.trim())
    .filter((p) => p.length >= MIN_TITLE);
  return [...new Set(parts)];
}

function ProcessLabel({ process }: { process: string }) {
  if (process === ANY_PROCESS) {
    return (
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex size-[30px] shrink-0 items-center justify-center rounded-[8px] bg-surface-2 text-muted [&>svg]:size-4">
          <AppWindow />
        </span>
        <div className="min-w-0">
          <div className="truncate text-[13.5px] font-medium text-fg">{t("titleRules.anyApp")}</div>
          <div className="truncate font-mono text-[11.5px] text-subtle">*</div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex min-w-0 items-center gap-3">
      <AppIcon process={process} size={30} />
      <div className="min-w-0">
        <div className="truncate text-[13.5px] font-medium text-fg">{appName(process)}</div>
        <div className="truncate font-mono text-[11.5px] text-subtle">{process}</div>
      </div>
    </div>
  );
}

export function TitleRulesBlock() {
  const { styles } = useCore();
  const toast = useToast();
  const rules = useLoad(() => call("title_rules_list"));
  const [adding, setAdding] = useState(false);
  const syncSeq = useRef(0);

  /**
   * После изменения — список ядра, а не догадка по своему ключу: какое правило «то же самое»,
   * решает ядро. Ответ устаревшего перечитывания (правки подряд) не применяется.
   */
  const resync = async (fallback: (xs: TitleRule[]) => TitleRule[]) => {
    const seq = ++syncSeq.current;
    try {
      const fresh = await call("title_rules_list");
      if (seq === syncSeq.current) rules.setData(() => fresh);
    } catch {
      if (seq === syncSeq.current) rules.setData((xs) => fallback(xs ?? []));
    }
  };

  const upsert = async (rule: TitleRule): Promise<boolean> => {
    const prev = rules.data;
    const k = ruleKey(rule);
    rules.setData((xs) => {
      const arr = xs ?? [];
      const idx = arr.findIndex((r) => ruleKey(r) === k);
      if (idx < 0) return [...arr, rule];
      const copy = [...arr];
      copy[idx] = rule;
      return copy;
    });
    try {
      const saved = await call("title_rule_upsert", rule);
      await resync((xs) => xs.map((r) => (ruleKey(r) === k ? saved : r)));
      return true;
    } catch (e) {
      rules.setData(() => prev);
      toast({ tone: "error", title: t("errors.save"), description: errorText(e) });
      return false;
    }
  };

  const remove = async (rule: TitleRule) => {
    const prev = rules.data;
    rules.setData((xs) => (xs ?? []).filter((r) => ruleKey(r) !== ruleKey(rule)));
    try {
      await call("title_rule_delete", { process: rule.process, title: rule.title });
      void resync((xs) => xs);
      toast({
        tone: "info",
        title: t("titleRules.deleted", { title: rule.title }),
        action: { label: t("common.undo"), onClick: () => void upsert(rule) },
      });
    } catch (e) {
      rules.setData(() => prev);
      toast({ tone: "error", title: t("errors.generic"), description: errorText(e) });
    }
  };

  const modeOptions: SelectOption<InsertMode | null>[] = [
    { value: null, label: t("titleRules.inherit") },
    { value: "auto", label: t("insertModes.auto") },
    { value: "type", label: t("insertModes.type") },
    { value: "clipboard", label: t("insertModes.clipboard") },
  ];
  const styleOptions: SelectOption<string | null>[] = [
    { value: null, label: t("titleRules.inherit") },
    ...styles.map((s) => ({ value: s.id, label: s.name, icon: STYLE_ICONS[s.id] })),
  ];

  const list = [...(rules.data ?? [])].sort(sortRules);

  return (
    <section className="mt-9" data-testid="title-rules">
      <SectionTitle
        hint={t("titleRules.hint")}
        right={
          <Button size="sm" variant="secondary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
            {t("titleRules.add")}
          </Button>
        }
      >
        {t("titleRules.title")}
      </SectionTitle>

      {rules.loading && !rules.data ? (
        <Card padded={false}>
          {[0, 1].map((i) => (
            <div key={i} className="flex items-center gap-4 border-b border-line px-5 py-3.5 last:border-0">
              <Skeleton className="size-8" />
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-4 w-40" />
              <Skeleton className="ml-auto h-8 w-36" />
              <Skeleton className="h-8 w-40" />
            </div>
          ))}
        </Card>
      ) : rules.error && !rules.data ? (
        <Card>
          <LoadError compact error={rules.error} onRetry={rules.reload} />
        </Card>
      ) : list.length === 0 ? (
        <Card>
          <EmptyState
            compact
            icon={<TextSearch />}
            title={t("titleRules.empty.title")}
            text={t("titleRules.empty.text")}
            action={
              <Button variant="secondary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
                {t("titleRules.add")}
              </Button>
            }
          />
        </Card>
      ) : (
        <Card padded={false} className="overflow-hidden">
          <div className="grid grid-cols-[170px_minmax(0,1fr)_170px_190px_36px] items-center gap-3 border-b border-line bg-surface-2/60 px-5 py-2.5 text-[12px] font-medium text-subtle">
            <span>{t("titleRules.cols.app")}</span>
            <span>{t("titleRules.cols.title")}</span>
            <span>{t("apps.cols.mode")}</span>
            <span>{t("apps.cols.style")}</span>
            <span />
          </div>
          <AnimatePresence initial={false}>
            {list.map((r) => (
              <motion.div
                key={ruleKey(r)}
                layout="position"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.18 }}
                className="border-b border-line last:border-b-0"
              >
                <div className="grid grid-cols-[170px_minmax(0,1fr)_170px_190px_36px] items-center gap-3 px-5 py-3">
                  <ProcessLabel process={r.process} />
                  <div className="min-w-0">
                    <span
                      className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-accent-soft px-2 py-1 text-[13px] font-medium text-accent-text"
                      title={r.title}
                    >
                      <TextSearch className="size-3.5 shrink-0" />
                      <span className="truncate">{r.title}</span>
                    </span>
                  </div>
                  <Select size="sm" value={r.insert_mode} options={modeOptions} onChange={(v) => void upsert({ ...r, insert_mode: v })} />
                  <Select size="sm" value={r.style} options={styleOptions} onChange={(v) => void upsert({ ...r, style: v })} />
                  <IconButton label={t("common.delete")} size="sm" tone="danger" onClick={() => void remove(r)}>
                    <Trash className="size-3.5" />
                  </IconButton>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </Card>
      )}

      <TitleRuleDialog
        open={adding}
        existing={rules.data ?? []}
        modeOptions={modeOptions}
        styleOptions={styleOptions}
        onClose={() => setAdding(false)}
        onSave={async (rule) => {
          const ok = await upsert(rule);
          if (ok) {
            setAdding(false);
            toast({ tone: "success", title: t("titleRules.added", { title: rule.title }) });
          }
        }}
      />
    </section>
  );
}

function TitleRuleDialog({
  open,
  existing,
  modeOptions,
  styleOptions,
  onClose,
  onSave,
}: {
  open: boolean;
  existing: TitleRule[];
  modeOptions: SelectOption<InsertMode | null>[];
  styleOptions: SelectOption<string | null>[];
  onClose: () => void;
  onSave: (r: TitleRule) => Promise<void>;
}) {
  const recent = useLoad(() => (open ? call("recent_apps") : Promise.resolve([] as RecentApp[])), [open]);
  const rdp = useRdpWindows();
  const [process, setProcess] = useState<string>(ANY_PROCESS);
  const [manualProcess, setManualProcess] = useState("");
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<InsertMode | null>(null);
  const [style, setStyle] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setProcess(ANY_PROCESS);
    setManualProcess("");
    setTitle("");
    setMode(null);
    setStyle(null);
    setSubmitted(false);
    setBusy(false);
    reloadRdp();
  }, [open]);

  const apps = recent.data ?? [];
  const sessions = rdp.windows ?? [];

  const locale = useLocale();
  const processOptions = useMemo<SelectOption<string>[]>(() => {
    const seen = new Set<string>();
    const opts: SelectOption<string>[] = [{ value: ANY_PROCESS, label: t("titleRules.anyApp"), icon: <AppWindow /> }];
    const push = (p: string) => {
      const v = p.toLowerCase();
      if (!v || seen.has(v)) return;
      seen.add(v);
      opts.push({ value: v, label: appName(v), hint: v, icon: <AppIcon process={v} size={18} /> });
    };
    for (const w of sessions) push(w.process);
    for (const a of apps) push(a.process);
    opts.push({ value: OTHER, label: t("titleRules.otherApp") });
    return opts;
  }, [apps, sessions, locale]);

  const proc = process === OTHER ? normalizeProcess(manualProcess) : process;
  const trimmed = title.trim();
  const dup = existing.some((r) => ruleKey(r) === ruleKey({ process: proc, title: trimmed }));
  const error = !proc
    ? t("titleRules.errors.process")
    : trimmed.length < MIN_TITLE
      ? t("titleRules.errors.short", { n: MIN_TITLE })
      : dup
        ? t("titleRules.errors.dup")
        : mode === null && style === null
          ? t("titleRules.errors.nothing")
          : null;
  const shownError = submitted ? error : dup ? error : null;

  // Подсказки: открытые RDP-сессии (ключ — имя сервера) и недавние заголовки выбранного процесса
  const suggestApps = apps.filter(
    (a) => (process === ANY_PROCESS || process === OTHER || a.process.toLowerCase() === process) && titlesOf(a).length > 0,
  );

  // Подсказка задаёт и приложение, откуда она взята (потом можно выбрать «Любое приложение»)
  const pick = (p: string, value: string) => {
    setProcess(p.toLowerCase());
    setTitle(value);
  };

  const submit = async () => {
    setSubmitted(true);
    if (error) return;
    setBusy(true);
    await onSave({ process: proc, title: trimmed, insert_mode: mode, style });
    setBusy(false);
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("titleRules.dialog.title")}
      width={600}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" loading={busy} disabled={shownError !== null} onClick={() => void submit()}>
            {t("titleRules.dialog.save")}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-[210px_minmax(0,1fr)] gap-3">
        <div>
          <div className="mb-1.5 text-[12px] font-medium text-muted">{t("titleRules.cols.app")}</div>
          <Select value={process} options={processOptions} onChange={setProcess} minWidth={260} className="w-full" />
        </div>
        <div>
          <div className="mb-1.5 text-[12px] font-medium text-muted">{t("titleRules.cols.title")}</div>
          <Input
            autoFocus
            value={title}
            placeholder={t("titleRules.dialog.titlePlaceholder")}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void submit()}
          />
        </div>
      </div>
      {process === OTHER && (
        <Input
          className="mt-2"
          value={manualProcess}
          placeholder={t("apps.dialog.manualPlaceholder")}
          onChange={(e) => setManualProcess(e.target.value)}
        />
      )}
      <div className="mt-2 flex items-start gap-1.5 text-[12px] leading-relaxed text-subtle">
        <Globe className="mt-[2px] size-3.5 shrink-0" />
        <span>{t("titleRules.dialog.browserHint")}</span>
      </div>

      <div className="mt-4 mb-2 flex items-center justify-between">
        <span className="text-[12.5px] font-medium text-muted">{t("titleRules.dialog.pick")}</span>
        <IconButton
          size="sm"
          label={t("common.refresh")}
          onClick={() => {
            recent.reload();
            reloadRdp();
          }}
        >
          <RefreshCw className={cn("size-3.5", (recent.loading || rdp.loading) && "animate-spin")} />
        </IconButton>
      </div>
      <div className="max-h-[240px] overflow-y-auto rounded-xl border border-line">
        {recent.loading && !recent.data ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : sessions.length === 0 && suggestApps.length === 0 ? (
          <div className="px-4 py-7 text-center text-[13px] text-subtle">{t("titleRules.dialog.noWindows")}</div>
        ) : (
          <>
            {sessions.length > 0 && (
              <div className="border-b border-line px-3.5 py-2.5 last:border-b-0">
                <div className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-medium uppercase tracking-wide text-subtle">
                  <Monitor className="size-3.5" />
                  {t("titleRules.dialog.rdp")}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {sessions.map((w) => (
                    <Chip key={w.key} active={foldTitle(trimmed) === foldTitle(w.key)} title={w.title} onClick={() => pick(w.process, w.key)}>
                      {w.key}
                    </Chip>
                  ))}
                </div>
              </div>
            )}
            {suggestApps.map((a) => (
              <div key={a.process} className="border-b border-line px-3.5 py-2.5 last:border-b-0">
                <div className="mb-1.5 flex items-center gap-2">
                  <AppIcon process={a.process} size={18} />
                  <span className="text-[12.5px] font-medium text-fg">{appName(a.process)}</span>
                  <span className="font-mono text-[11px] text-subtle">{a.process}</span>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {chipsOf(a).map(({ part, full }) => (
                    <Chip
                      key={part}
                      active={foldTitle(trimmed) === foldTitle(part)}
                      title={full}
                      onClick={() => pick(a.process, part)}
                    >
                      {part}
                    </Chip>
                  ))}
                </div>
              </div>
            ))}
          </>
        )}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <div>
          <div className="mb-1.5 text-[12px] font-medium text-muted">{t("apps.cols.mode")}</div>
          <Select value={mode} options={modeOptions} onChange={setMode} className="w-full" />
        </div>
        <div>
          <div className="mb-1.5 text-[12px] font-medium text-muted">{t("apps.cols.style")}</div>
          <Select value={style} options={styleOptions} onChange={setStyle} className="w-full" />
        </div>
      </div>
      <AnimatePresence initial={false}>
        {shownError && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="mt-3 rounded-lg bg-warn/10 px-3 py-2 text-[12.5px] text-warn" role="alert">
              {shownError}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Modal>
  );
}

function titlesOf(a: RecentApp): string[] {
  const list = a.titles?.length ? a.titles : a.title ? [a.title] : [];
  return [...new Set(list.filter((x) => x.trim().length >= MIN_TITLE))].slice(0, 10);
}

/**
 * Подсказки одного приложения: части его недавних заголовков без повторов
 * («Telegram — Анна», «Telegram — Дежурные» → Telegram, Анна, Дежурные).
 */
function chipsOf(a: RecentApp): { part: string; full: string }[] {
  const seen = new Set<string>();
  const out: { part: string; full: string }[] = [];
  for (const full of titlesOf(a)) {
    for (const part of titleParts(full)) {
      const k = foldTitle(part);
      if (seen.has(k)) continue;
      seen.add(k);
      out.push({ part, full });
    }
  }
  return out.slice(0, 16);
}

function normalizeProcess(p: string): string {
  let v = p.trim().toLowerCase();
  if (!v) return "";
  if (v !== ANY_PROCESS && !/\.exe$/.test(v)) v += ".exe";
  return v;
}

function Chip({
  children,
  onClick,
  active,
  title,
}: {
  children: string;
  onClick: () => void;
  active?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={cn(
        "max-w-full truncate rounded-md border px-2 py-0.5 text-[12.5px] transition-colors",
        active
          ? "border-accent/60 bg-accent-soft text-accent-text"
          : "border-line bg-surface-2 text-fg hover:border-accent/50 hover:text-accent-text",
      )}
    >
      {children}
    </button>
  );
}
