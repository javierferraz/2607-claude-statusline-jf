# Claude Statusline JF

Extensión de VS Code que muestra en la barra de estado el uso de Claude Code: modelo activo, % de uso de la sesión (5h) con cuenta atrás y hora de reset, % de uso semanal (7 días) con día/hora de reset, y el plan de contratación (Pro/Max/etc.).

Los datos se leen directamente de tus propias credenciales locales de Claude Code (`~/.claude/.credentials.json`) y de la API de uso de Anthropic — cada persona ve solo sus propios datos, no hay nada compartido ni embebido en la extensión.

## Instalación

1. Descarga el `.vsix` de la [última release](../../releases/latest).
2. En VS Code: panel de Extensiones (`Ctrl+Shift+X`) → menú `...` (arriba a la derecha) → **Install from VSIX...** → selecciona el fichero descargado.
   - O por terminal: `code --install-extension claude-statusline-2-X.X.X.vsix`
3. `Ctrl+Shift+P` → `Developer: Reload Window`.

## Desarrollo

```
npm install
npm run compile
npx @vscode/vsce package
```

Genera un `.vsix` en la raíz del proyecto, instalable con `code --install-extension <fichero> --force`.
