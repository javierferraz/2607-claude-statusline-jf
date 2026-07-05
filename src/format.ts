const DIAS_ES = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];

function toDate(resetsAt: string | number | undefined | null): Date | null {
  if (resetsAt === undefined || resetsAt === null || resetsAt === '') {
    return null;
  }
  const n = Number(resetsAt);
  const ms = !isNaN(n) && isFinite(n) ? (n < 1e10 ? n * 1000 : n) : new Date(resetsAt).getTime();
  return isFinite(ms) ? new Date(ms) : null;
}

export function formatCountdown(resetsAt: string | number | undefined | null): string {
  const d = toDate(resetsAt);
  if (!d) {
    return '';
  }
  const ms = d.getTime() - Date.now();
  if (ms <= 0) {
    return '';
  }
  const totalMins = Math.floor(ms / 60000);
  if (totalMins < 60) {
    return `${totalMins}m`;
  }
  const h = Math.floor(totalMins / 60);
  const m = totalMins % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

export function formatResetClock(resetsAt: string | number | undefined | null): string {
  const d = toDate(resetsAt);
  if (!d) {
    return '';
  }
  const hh = d.getHours().toString().padStart(2, '0');
  const mm = d.getMinutes().toString().padStart(2, '0');
  return `${hh}:${mm}`;
}

export function formatWeeklyReset(resetsAt: string | number | undefined | null): string {
  const d = toDate(resetsAt);
  if (!d) {
    return '';
  }
  return `${DIAS_ES[d.getDay()]}, ${d.getHours()}h`;
}

export function prettifyModelName(raw: string | undefined | null): string {
  if (!raw || raw === 'Claude') {
    return 'Claude';
  }
  let s = raw.replace(/\[\d+[kmb]?\]$/i, '').trim();
  s = s.replace(/-\d{8}$/, '').replace(/-latest$/, '');
  s = s.replace(/^claude-/, '');
  const m = s.match(/^(sonnet|opus|haiku)-(\d+)(?:-(\d+))?/i);
  if (m) {
    const fam = m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
    return m[3] ? `${fam} ${m[2]}.${m[3]}` : `${fam} ${m[2]}`;
  }
  return s.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function mapPlanLabel(raw: string | undefined | null): string {
  if (!raw) {
    return '';
  }
  const labels: Record<string, string> = { pro: 'Pro', team: 'Team', enterprise: 'Ent', free: 'Free' };
  return labels[raw] ?? raw.charAt(0).toUpperCase() + raw.slice(1);
}
