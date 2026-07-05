import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { mapPlanLabel } from './format';

const CLAUDE_DIR = path.join(os.homedir(), '.claude');
const CREDENTIALS_PATH = path.join(CLAUDE_DIR, '.credentials.json');

export interface OAuthUsage {
  five_hour?: { utilization: number; resets_at: string | number };
  seven_day?: { utilization: number; resets_at: string | number };
}

export interface StatusData {
  model: string;
  r5Pct?: number;
  r5ResetsAt?: string | number;
  r7Pct?: number;
  r7ResetsAt?: string | number;
  plan: string;
}

function readCredentials(): { accessToken?: string; subscriptionType?: string } | null {
  try {
    if (!fs.existsSync(CREDENTIALS_PATH)) {
      return null;
    }
    const creds = JSON.parse(fs.readFileSync(CREDENTIALS_PATH, 'utf8'));
    return {
      accessToken: creds?.claudeAiOauth?.accessToken,
      subscriptionType: creds?.claudeAiOauth?.subscriptionType,
    };
  } catch {
    return null;
  }
}

export interface ApiCacheState {
  data?: OAuthUsage;
  ts?: number;
  rateLimitedUntil?: number;
}

async function fetchOAuthUsage(token: string, cacheSeconds: number, state: ApiCacheState): Promise<OAuthUsage | null> {
  const now = Date.now();
  if (state.data && state.ts !== undefined && now / 1000 - state.ts < cacheSeconds) {
    return state.data;
  }
  if (state.rateLimitedUntil && now < state.rateLimitedUntil) {
    return state.data ?? null;
  }
  try {
    const res = await fetch('https://api.anthropic.com/api/oauth/usage', {
      headers: {
        Authorization: `Bearer ${token}`,
        'anthropic-beta': 'oauth-2025-04-20',
        'Content-Type': 'application/json',
      },
      signal: AbortSignal.timeout(8000),
    });
    if (res.status === 429) {
      const retryAfter = Number(res.headers.get('retry-after'));
      const backoffSec = !isNaN(retryAfter) && retryAfter > 0 ? retryAfter : 300;
      state.rateLimitedUntil = now + backoffSec * 1000;
      return state.data ?? null;
    }
    if (!res.ok) {
      return state.data ?? null;
    }
    const json = (await res.json()) as OAuthUsage;
    if (json.five_hour || json.seven_day) {
      state.data = json;
      state.ts = now / 1000;
      state.rateLimitedUntil = 0;
      return json;
    }
    return state.data ?? null;
  } catch {
    return state.data ?? null;
  }
}

interface TranscriptRef {
  file: string;
  mtime: number;
  matchesCwd: boolean;
}

function findTranscripts(cwd: string): string[] {
  const roots = [path.join(os.homedir(), '.claude', 'projects'), path.join(os.homedir(), '.config', 'claude', 'projects')];
  const files: TranscriptRef[] = [];
  const cwdSeg = path.basename(cwd).toLowerCase();
  const walk = (dir: string) => {
    try {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, e.name);
        if (e.isDirectory()) {
          walk(full);
        } else if (e.name.endsWith('.jsonl')) {
          const { mtimeMs } = fs.statSync(full);
          files.push({ file: full, mtime: mtimeMs, matchesCwd: path.dirname(full).toLowerCase().includes(cwdSeg) });
        }
      }
    } catch {
      /* skip unreadable directory */
    }
  };
  roots.forEach(walk);
  return files
    .sort((a, b) => (a.matchesCwd === b.matchesCwd ? b.mtime - a.mtime : a.matchesCwd ? -1 : 1))
    .map((f) => f.file);
}

function parseTranscriptModel(filePath: string): string {
  try {
    const lines = fs.readFileSync(filePath, 'utf8').trim().split('\n').filter(Boolean);
    for (let i = lines.length - 1; i >= 0; i--) {
      try {
        const e = JSON.parse(lines[i]);
        const c = e.message?.model || e.model || null;
        if (c && typeof c === 'string' && c.startsWith('claude')) {
          return c;
        }
      } catch {
        /* skip malformed line */
      }
    }
  } catch {
    /* skip unreadable file */
  }
  return '';
}

function findCurrentModel(cwd: string): string {
  const transcripts = findTranscripts(cwd);
  const newest = transcripts.find((t) => !t.includes(`${path.sep}subagents${path.sep}`) && !t.includes('/subagents/'));
  return newest ? parseTranscriptModel(newest) : '';
}

export async function getStatusData(cwd: string, apiCacheSeconds: number, cacheState: ApiCacheState): Promise<StatusData> {
  const creds = readCredentials();
  const plan = mapPlanLabel(creds?.subscriptionType);
  const rawModel = findCurrentModel(cwd);

  let r5Pct: number | undefined;
  let r5ResetsAt: string | number | undefined;
  let r7Pct: number | undefined;
  let r7ResetsAt: string | number | undefined;

  if (creds?.accessToken) {
    const usage = await fetchOAuthUsage(creds.accessToken, apiCacheSeconds, cacheState);
    if (usage?.five_hour) {
      r5Pct = Math.round(usage.five_hour.utilization);
      r5ResetsAt = usage.five_hour.resets_at;
    }
    if (usage?.seven_day) {
      r7Pct = Math.round(usage.seven_day.utilization);
      r7ResetsAt = usage.seven_day.resets_at;
    }
  }

  return { model: rawModel, r5Pct, r5ResetsAt, r7Pct, r7ResetsAt, plan };
}
