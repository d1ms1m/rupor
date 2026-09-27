import { animate } from "framer-motion";
import { useEffect, useLayoutEffect, useRef } from "react";
import { useLocale } from "../i18n";

/** Число с плавным «набегом» при появлении и изменении. */
export function CountUp({ value, format }: { value: number; format: (v: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const shown = useRef(0);
  const fmt = useRef(format);
  fmt.current = format;

  useLayoutEffect(() => {
    if (ref.current && !ref.current.textContent) ref.current.textContent = fmt.current(shown.current);
  }, []);

  // Сменился язык — то же число в новом формате («48 214» → "48,214"), без анимации
  const locale = useLocale();
  const firstLocale = useRef(locale);
  useLayoutEffect(() => {
    if (locale === firstLocale.current) return;
    firstLocale.current = locale;
    if (ref.current) ref.current.textContent = fmt.current(shown.current);
  }, [locale]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const from = shown.current;
    const controls = animate(from, value, {
      duration: from === 0 ? 0.8 : 0.45,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => {
        shown.current = v;
        el.textContent = fmt.current(v);
      },
    });
    return () => controls.stop();
  }, [value]);

  return <span ref={ref} className="tabular" />;
}
