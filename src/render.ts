import * as vscode from 'vscode';
import { StatusData } from './dataSource';
import { formatCountdown, formatResetClock, formatWeeklyReset, prettifyModelName } from './format';

export function renderStatusBar(item: vscode.StatusBarItem, data: StatusData): void {
  const segments: string[] = [];

  const model = prettifyModelName(data.model);
  if (model) {
    segments.push(model);
  }

  if (data.r5Pct !== undefined) {
    const countdown = formatCountdown(data.r5ResetsAt);
    const clock = formatResetClock(data.r5ResetsAt);
    const parts = [`${data.r5Pct}%`, countdown, clock ? `(${clock})` : ''].filter(Boolean);
    segments.push(`$(pulse) Sesión ${parts.join(' · ')}`);
  }

  if (data.r7Pct !== undefined) {
    const weeklyReset = formatWeeklyReset(data.r7ResetsAt);
    const parts = [`${data.r7Pct}%`, weeklyReset].filter(Boolean);
    segments.push(`$(calendar) Semana ${parts.join(' · ')}`);
  }

  if (data.plan) {
    segments.push(`$(rocket) ${data.plan}`);
  }

  item.text = segments.length ? segments.join('  │  ') : 'Claude $(warning)';

  const usagePct = Math.max(data.r5Pct ?? 0, data.r7Pct ?? 0);
  item.backgroundColor = usagePct >= 80
    ? new vscode.ThemeColor('statusBarItem.errorBackground')
    : new vscode.ThemeColor('statusBarItem.warningBackground');

  const md = new vscode.MarkdownString();
  md.supportThemeIcons = true;
  md.appendMarkdown(`## Claude Statusline JF\n\n`);
  md.appendMarkdown(`| | |\n|---|---|\n`);
  md.appendMarkdown(`| **Modelo** | \`${model || 'desconocido'}\` |\n`);
  if (data.r5Pct !== undefined) {
    const countdown = formatCountdown(data.r5ResetsAt);
    const clock = formatResetClock(data.r5ResetsAt);
    md.appendMarkdown(`| **Sesión (5h)** | **${data.r5Pct}%**${countdown ? ` — restablece en ${countdown}` : ''}${clock ? ` (${clock})` : ''} |\n`);
  }
  if (data.r7Pct !== undefined) {
    const weeklyReset = formatWeeklyReset(data.r7ResetsAt);
    md.appendMarkdown(`| **Semana (7 días)** | **${data.r7Pct}%**${weeklyReset ? ` — restablece el ${weeklyReset}` : ''} |\n`);
  }
  if (data.plan) {
    md.appendMarkdown(`| **Plan** | \`${data.plan}\` |\n`);
  }
  md.appendMarkdown(`\n---\n[$(refresh) Refresh](command:claudeStatusline2.refreshNow)`);
  md.isTrusted = true;
  item.tooltip = md;
}
