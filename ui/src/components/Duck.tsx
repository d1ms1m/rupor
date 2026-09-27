// «Настройки → Диктовка → Звук компьютера во время записи» (duck_mode / duck_level).
// Ядро на время записи приглушает или выключает звук других приложений (аудиосессии
// Core Audio) и возвращает прежнюю громкость после; свои звуки и системные не трогает.
import { AnimatePresence, motion } from "framer-motion";
import { Info, Volume1, Volume2, VolumeX } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { t } from "../i18n";
import type { DuckMode, Settings, SettingsPatch } from "../lib/types";
import { Segmented, Slider } from "./ui/controls";
import { Card, SectionTitle, SettingRow } from "./ui/display";

/** Значения ядра по умолчанию — на случай, если старое ядро их ещё не присылает. */
export const DUCK_DEFAULT_MODE: DuckMode = "duck";
export const DUCK_DEFAULT_LEVEL = 15;

const MODES: DuckMode[] = ["off", "duck", "mute"];
const ICONS: Record<DuckMode, ReactNode> = {
  off: <Volume2 className="size-3.5" />,
  duck: <Volume1 className="size-3.5" />,
  mute: <VolumeX className="size-3.5" />,
};

/** Пример в подсказке: во что превратится громкость 80 % при выбранном уровне. */
const EXAMPLE_VOLUME = 80;

export function DuckSection({
  s,
  set,
}: {
  s: Pick<Settings, "duck_mode" | "duck_level">;
  set: (p: SettingsPatch) => Promise<boolean>;
}) {
  const mode: DuckMode = MODES.includes(s.duck_mode) ? s.duck_mode : DUCK_DEFAULT_MODE;
  const saved = s.duck_level ?? DUCK_DEFAULT_LEVEL;
  // Ползунок двигается локально, в ядро уходит только отпущенное значение
  const [level, setLevel] = useState(saved);
  useEffect(() => setLevel(saved), [saved]);

  return (
    <section>
      <SectionTitle hint={t("settings.dictation.duck.hint")}>{t("settings.dictation.duck.title")}</SectionTitle>
      <Card padded={false}>
        <SettingRow title={t("settings.dictation.duck.mode")} description={t(`settings.dictation.duck.modeHints.${mode}`)}>
          <Segmented<DuckMode>
            value={mode}
            size="sm"
            onChange={(v) => v !== mode && void set({ duck_mode: v })}
            options={MODES.map((m) => ({ value: m, label: t(`settings.dictation.duck.modes.${m}`), icon: ICONS[m] }))}
          />
        </SettingRow>
        <AnimatePresence initial={false}>
          {mode === "duck" && (
            <motion.div
              key="level"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.18 }}
              className="overflow-hidden"
            >
              <SettingRow
                title={t("settings.dictation.duck.level")}
                description={t("settings.dictation.duck.levelHint", {
                  n: Math.round((EXAMPLE_VOLUME * level) / 100),
                })}
              >
                <Slider
                  className="w-[260px]"
                  label={t("settings.dictation.duck.level")}
                  value={level}
                  min={0}
                  max={100}
                  step={5}
                  onChange={setLevel}
                  onCommit={(v) => v !== saved && void set({ duck_level: v })}
                  format={(v) => t("settings.dictation.duck.levelValue", { n: v })}
                />
              </SettingRow>
            </motion.div>
          )}
        </AnimatePresence>
      </Card>
      <p className="mt-2.5 flex gap-2 px-1 text-[12px] leading-relaxed text-subtle">
        <Info className="mt-[3px] size-3.5 shrink-0" />
        <span>{t("settings.dictation.duck.note")}</span>
      </p>
    </section>
  );
}
