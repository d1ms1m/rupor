import { useState } from "react";
import { t } from "../i18n";
import type { Settings, SettingsPatch } from "../lib/types";
import { CommitInput } from "./fields";
import { KeyManager } from "./KeyManager";
import { Button, Textarea } from "./ui/controls";
import { SettingRow } from "./ui/display";

export function OpenAISettings({ s, set }: { s: Settings; set: (p: SettingsPatch) => Promise<boolean> }) {
  // A local draft survives optimistic settings updates and failed saves.
  const [draft, setDraft] = useState<string | null>(null);
  const json = draft ?? (s.openai_extra_json === "{}" ? "" : s.openai_extra_json);
  const [saving, setSaving] = useState(false);
  const [priceError, setPriceError] = useState(false);
  const saveJson = async () => {
    const submitted = json.trim() || "{}";
    setSaving(true);
    try {
      if (await set({ openai_extra_json: submitted })) {
        // Do not discard edits made while this save was pending.
        setDraft((current) => (current?.trim() || "{}") === submitted ? null : current);
      }
    } finally {
      setSaving(false);
    }
  };
  return (
    <>
      <SettingRow title={t("settings.ai.openaiUrl")} description={t("settings.ai.openaiUrlHint")}>
        <CommitInput mono className="w-[300px]" value={s.openai_base_url} placeholder="https://api.deepseek.com"
          onCommit={(v) => void set({ openai_base_url: v })} />
      </SettingRow>
      <SettingRow title={t("settings.ai.model")} description={t("settings.ai.openaiModelHint")}>
        <CommitInput mono className="w-[300px]" value={s.openai_model} placeholder="deepseek-flash"
          onCommit={(v) => void set({ openai_model: v })} />
      </SettingRow>
      <SettingRow stacked title={t("settings.ai.key")} description={t("settings.ai.openaiKeyHint")}>
        <KeyManager provider="openai_compatible" />
      </SettingRow>
      <SettingRow stacked title={t("settings.ai.openaiExtra")} description={t("settings.ai.openaiExtraHint")}>
        <Textarea aria-label={t("settings.ai.openaiExtra")} className="min-h-28 font-mono text-[12.5px]" value={json}
          onChange={(e) => setDraft(e.target.value)} spellCheck={false} placeholder={'{"thinking":{"type":"disabled"}}'} />
        <Button size="sm" variant="secondary" className="mt-2" loading={saving}
          disabled={(json.trim() || "{}") === s.openai_extra_json} onClick={() => void saveJson()}>
          {t("common.save")}
        </Button>
      </SettingRow>
      <SettingRow stacked title={t("settings.ai.openaiPrices")} description={t("settings.ai.openaiPricesHint")}>
        <div className="flex flex-wrap gap-3">
          {(["openai_input_price", "openai_output_price", "openai_cached_input_price"] as const).map((field) => (
            <label key={field} className="space-y-1 text-[12px] text-muted">
              <span className="block">{t(`settings.ai.${field}`)}</span>
              <CommitInput mono className="w-[160px]" value={s[field]?.toString() ?? ""} placeholder={t("settings.ai.priceUnset")}
                onCommit={(v) => {
                  const n = v === "" ? null : Number(v.replace(",", "."));
                  if (n !== null && (!Number.isFinite(n) || n < 0)) { setPriceError(true); return; }
                  setPriceError(false);
                  void set({ [field]: n });
                }} />
            </label>
          ))}
        </div>
        {priceError && <div role="alert" className="mt-2 text-[12px] text-danger">{t("settings.ai.priceInvalid")}</div>}
      </SettingRow>
    </>
  );
}
