// График слов за 30 дней (Главная).
import { tp } from "../i18n";
import { fmtNum } from "../lib/format";
import type { DailyWords } from "../lib/types";
import { DayBars } from "./DayBars";

const words = (d: DailyWords) => d.words;
const tip = (d: DailyWords) => tp("units.words", d.words);

export function WordsChart({ data }: { data: DailyWords[] }) {
  return <DayBars data={data} value={words} axisFormat={fmtNum} tooltip={tip} emptyMax={100} />;
}
