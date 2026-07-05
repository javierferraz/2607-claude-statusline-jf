import * as vscode from 'vscode';
import * as os from 'os';
import { getStatusData, StatusData, ApiCacheState } from './dataSource';
import { renderStatusBar } from './render';

const FAST_TICK_MS = 20_000;
const CACHE_STATE_KEY = 'apiCacheState';

export function activate(context: vscode.ExtensionContext): void {
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  item.command = 'claudeStatusline2.refreshNow';
  item.text = '$(hubot) Claude…';
  item.show();

  let lastData: StatusData | null = null;
  const cacheState: ApiCacheState = context.globalState.get<ApiCacheState>(CACHE_STATE_KEY, {});

  const cwd = () => vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? os.homedir();

  const cfg = () => vscode.workspace.getConfiguration('claudeStatusline2');

  const refreshData = async () => {
    try {
      lastData = await getStatusData(cwd(), cfg().get<number>('apiCacheSeconds', 60), cacheState);
      await context.globalState.update(CACHE_STATE_KEY, cacheState);
      renderStatusBar(item, lastData);
    } catch (e) {
      item.text = '$(hubot) Claude $(error)';
      item.tooltip = `Error: ${e}`;
    }
  };

  const rerender = () => {
    if (lastData) {
      renderStatusBar(item, lastData);
    }
  };

  void refreshData();

  let slowTimer = setInterval(refreshData, cfg().get<number>('refreshIntervalSeconds', 60) * 1000);
  const fastTimer = setInterval(rerender, FAST_TICK_MS);

  context.subscriptions.push(
    vscode.commands.registerCommand('claudeStatusline2.refreshNow', refreshData),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('claudeStatusline2.refreshIntervalSeconds')) {
        clearInterval(slowTimer);
        slowTimer = setInterval(refreshData, cfg().get<number>('refreshIntervalSeconds', 60) * 1000);
      }
    }),
    item,
    { dispose: () => clearInterval(slowTimer) },
    { dispose: () => clearInterval(fastTimer) }
  );
}

export function deactivate(): void {
  // Intervals are cleared via context.subscriptions disposables.
}
