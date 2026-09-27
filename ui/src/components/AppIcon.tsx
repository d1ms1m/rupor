import {
  AppWindow,
  BookOpenText,
  CodeXml,
  FileText,
  Folder,
  Globe,
  Mail,
  MessageSquare,
  Monitor,
  NotebookPen,
  Send,
  SquareTerminal,
  Table2,
} from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../lib/cn";

const ICONS: [RegExp, ReactNode][] = [
  [/telegram/i, <Send key="tg" />],
  [/^(cursor|code|code - insiders|windsurf|idea64|pycharm64|devenv|zed)\.exe$/i, <CodeXml key="code" />],
  [/^(chrome|msedge|firefox|brave|opera|browser|vivaldi|arc)\.exe$/i, <Globe key="web" />],
  [/^(outlook|olk|thunderbird)\.exe$/i, <Mail key="mail" />],
  [/^(mstsc|mremoteng|rdcman|msrdc)\.exe$/i, <Monitor key="rdp" />],
  [/^(slack|discord|teams|ms-teams|whatsapp|zoom)\.exe$/i, <MessageSquare key="chat" />],
  [/^(winword|wordpad|notepad|notepad\+\+)\.exe$/i, <FileText key="doc" />],
  [/^excel\.exe$/i, <Table2 key="xls" />],
  [/^(obsidian|notion|onenote)\.exe$/i, <NotebookPen key="notes" />],
  [/^(windowsterminal|wt|cmd|powershell|pwsh|conhost)\.exe$/i, <SquareTerminal key="term" />],
  [/^explorer\.exe$/i, <Folder key="explorer" />],
  [/^(acrord32|sumatrapdf)\.exe$/i, <BookOpenText key="pdf" />],
];

function hue(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h % 360;
}

/** Иконка приложения: знакомые процессы — значком, остальные — буквой. */
export function AppIcon({ process, size = 28, className }: { process: string; size?: number; className?: string }) {
  const p = process.toLowerCase();
  const icon = ICONS.find(([re]) => re.test(p))?.[1];
  const h = hue(p || "?");
  const letter = (p.replace(/\.exe$/, "").match(/[\p{L}\p{N}]/u)?.[0] ?? "?").toUpperCase();
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-[8px] font-semibold [&>svg]:size-[55%]",
        className,
      )}
      style={{
        width: size,
        height: size,
        fontSize: size * 0.42,
        color: `hsl(${h} 62% 52%)`,
        background: `color-mix(in oklab, hsl(${h} 70% 55%) 15%, transparent)`,
      }}
    >
      {icon ?? (process ? letter : <AppWindow />)}
    </span>
  );
}
