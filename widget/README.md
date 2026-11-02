# Widget de escritorio · consumo de varias cuentas de Claude

Ventana pequeña para el escritorio (Python + tkinter, sin dependencias; solo la opción `--captura` usa Pillow) con, por cada cuenta:
email y organización, **sesión de 5 h** (% y hora de reset), **semana** (% y día/hora de reset) y
**mensual** (créditos extra, si la cuenta los tiene activos). Es independiente de la extensión de
VS Code de este repo y usa la misma fuente de datos (`src/dataSource.ts`).

## Cómo funciona

- Cada cuenta vive en su propia carpeta de configuración de Claude Code (`CLAUDE_CONFIG_DIR`).
  El widget lee `<carpeta>/.credentials.json` y consulta el servicio de uso de Anthropic
  (`/api/oauth/usage`) y el de perfil (`/api/oauth/profile`).
- Las cuentas con `"renovar": true` renuevan su token cuando caduca (mismo método que Claude Code,
  no documentado). La cuenta de `~/.claude` va con `false`: la renueva Claude Code al usarla.
- En las carpetas con `"renovar": true` no uses a la vez Claude Code: si los dos renuevan el token al mismo
  tiempo, uno se queda con un token inválido y hay que volver a iniciar sesión. Por lo mismo, solo se abre
  un widget a la vez.
- Refresca cada 60 s, con caché por cuenta y espera tras un 429. Si una cuenta no tiene datos,
  sale «no disponible» con el motivo; nunca se muestra un 0 % inventado. Si la API no responde, se
  enseña el último dato marcado en naranja como «dato de HH:MM».

## Instalación

1. `copy cuentas.example.json cuentas.json` y ajusta alias y carpetas (sin secretos; fuera de git).
2. Inicia sesión una vez en cada cuenta extra, cada una en su carpeta (PowerShell, una línea):
   `$env:CLAUDE_CONFIG_DIR="$HOME\.claude-cuenta2"; claude auth login; Remove-Item Env:CLAUDE_CONFIG_DIR`
3. Abre el widget con `lanzar-widget.vbs` (sin consola) o con el acceso directo «Claude cuentas».

Arrastra la cabecera para moverlo; 📌 activa o desactiva «siempre encima»; ⟳ refresca; ✕ cierra.
La posición se guarda en `%LOCALAPPDATA%\ClaudeCuentasWidget`.

## Pruebas

```
python -m unittest discover -s widget
python widget/claude_cuentas.py --captura captura.png
```

## Límites conocidos

- La API no da un consumo mensual del plan; «Mensual» solo muestra los créditos extra.
- Los servicios de uso y de renovación no son públicos: si Anthropic los cambia, las cuentas salen
  como «no disponible».
