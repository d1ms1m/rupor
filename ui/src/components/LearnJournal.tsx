// «Словарь → Недавно добавлено»: журнал обучения (dict_learn_journal) — что попало в словарь
// из ваших правок. Добавил сам Рупор (режим «Сразу добавлять» или повтор правки в режиме
// «Спрашивать») или вы нажали «Добавить» на его вопросе. У каждой записи — «Отменить»
// (dict_learn_undo, как кнопка в пилюле): так видно, как пополняется словарь, и любое
// добавление можно откатить и позже, когда уведомление уже исчезло.
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, BookCheck, ChevronDown, Undo2, UserRoundCheck } from "lucide-react";
import { useState } from "react";
import { t } from "../i18n";
import { fmtAgo, fmtDayLabel, fmtTime } from "../lib/format";
import { useNow } from "../lib/hooks";
import type { LearnJournalEntry } from "../lib/types";
import { Button } from "./ui/controls";
import { Badge, Card, SectionTitle } from "./ui/display";

/** Сколько записей журнала запрашивать у ядра (свежие сверху). */
export const JOURNAL_LIMIT = 50;
/** Сколько видно сразу; остальные — по «Показать ещё». */
const SHOWN = 10;

/**
 * Ключ строки: id термина в журнале не уникален (у термина может быть несколько выученных
 * вариантов), а у записей старых версий нет времени — одинаковые различаем по счётчику.
 */
function rowKeys(entries: LearnJournalEntry[]): string[] {
  const seen = new Map<string, number>();
  return entries.map((e) => {
    const base = [e.id, e.created ? 1 : 0, e.variant.toLowerCase(), e.ts ?? ""].join("\u0001");
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return `${base}\u0001${n}`;
  });
}

export function LearnJournal({
  entries,
  onUndo,
}: {
  /** Записи журнала, свежие сверху (пустой список — раздел не показывается). */
  entries: LearnJournalEntry[];
  onUndo: (entry: LearnJournalEntry) => void;
}) {
  const [all, setAll] = useState(false);
  // «5 мин назад» — обновлять, пока страница открыта
  const now = useNow(30_000, entries.length > 0);
  const shown = all ? entries : entries.slice(0, SHOWN);
  const keys = rowKeys(shown);

  return (
    <AnimatePresence initial={false}>
      {entries.length > 0 && (
        <motion.section
          key="journal"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.2 }}
          className="overflow-hidden"
          data-testid="dict-journal"
        >
          <div className="mb-6">
            <SectionTitle hint={t("dictionary.journal.hint")}>{t("dictionary.journal.title")}</SectionTitle>
            <Card padded={false} className="overflow-hidden">
              <AnimatePresence initial={false}>
                {shown.map((e, i) => (
                  <motion.div
                    key={keys[i]}
                    layout="position"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.18 }}
                    className="border-b border-line last:border-b-0"
                  >
                    <JournalRow entry={e} now={now} onUndo={() => onUndo(e)} />
                  </motion.div>
                ))}
              </AnimatePresence>
            </Card>
            {!all && entries.length > SHOWN && (
              <div className="mt-3 flex justify-center">
                <Button size="sm" variant="ghost" icon={<ChevronDown className="size-4" />} onClick={() => setAll(true)}>
                  {t("dictionary.journal.more")}
                </Button>
              </div>
            )}
          </div>
        </motion.section>
      )}
    </AnimatePresence>
  );
}

/** «вариант» → Термин, кто добавил, когда и «Отменить». */
function JournalRow({ entry: e, now, onUndo }: { entry: LearnJournalEntry; now: number; onUndo: () => void }) {
  const auto = e.source === "auto";
  return (
    <div className="flex items-center gap-4 px-5 py-3 transition-colors hover:bg-surface-2/50">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
        {e.variant && (
          <>
            <span className="inline-flex h-6 items-center rounded-md bg-surface-2 px-2 text-[12.5px] text-muted selectable">
              {e.variant}
            </span>
            <ArrowRight className="mx-0.5 size-3.5 text-subtle" />
          </>
        )}
        <span className="inline-flex h-6 items-center rounded-md bg-accent-soft px-2 text-[12.5px] font-medium text-accent-text selectable">
          {e.term}
        </span>
        {e.created && <span className="ml-1 text-[12px] text-subtle">{t("dictionary.journal.newTerm")}</span>}
      </div>
      {e.source && (
        <Badge
          tone={auto ? "accent" : "neutral"}
          icon={auto ? <BookCheck /> : <UserRoundCheck />}
          title={t(auto ? "dictionary.journal.sourceAutoHint" : "dictionary.journal.sourceAcceptedHint")}
        >
          {t(auto ? "dictionary.journal.sourceAuto" : "dictionary.journal.sourceAccepted")}
        </Badge>
      )}
      <span
        className="w-[88px] shrink-0 text-right text-[12px] text-subtle tabular"
        title={e.ts !== null ? `${fmtDayLabel(e.ts)}, ${fmtTime(e.ts)}` : undefined}
      >
        {e.ts !== null ? fmtAgo(e.ts, now) : ""}
      </span>
      <Button size="sm" variant="ghost" icon={<Undo2 className="size-3.5" />} onClick={onUndo}>
        {t("learn.undo")}
      </Button>
    </div>
  );
}
