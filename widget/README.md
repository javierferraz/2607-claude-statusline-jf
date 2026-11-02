# Cronos · widget de escritorio con el consumo de varias cuentas de Claude

Ventana pequeña para el escritorio (Python + tkinter, sin dependencias; solo la opción `--captura` usa Pillow) con, por cada cuenta:
nombre y email, el nivel **Max** del plan (discreto, junto al nombre), **sesión de 5 h** y **semana**
(% con barra y hora de reset). Es independiente de la extensión de VS Code de este repo y usa la
misma fuente de datos (`src/dataSource.ts`).

## Aspecto

Copia la estética de Roaring Lion (su `DESIGN.md`, paleta «Piedra»); la interfaz va en inglés, como Lion.

- **Tema oscuro por defecto, claro disponible** (botón ☀/🌙 de la barra de título; se recuerda).
- **Raya blanca** en cada barra = ritmo uniforme (la parte de la ventana ya gastada). **Color de la barra**
  = cuánto te adelantas a esa raya, con la regla de Lion (S-792): hasta 5 puntos = verde, hasta 15 = ámbar,
  más = rojo, ventana llena = rojo. Añadido en Cronos: **azul** si vas más de 25 puntos por debajo (sobra cuota).
- En la semana, «at this pace, out Tue 15:41» (rojo) si al ritmo medio la agotarías antes del reset.
- **Punto lima** tras el nombre = la cuenta que usa Claude Code en este PC (la carpeta `~/.claude`); al pasar el
  ratón lo explica. No toca el fondo de la fila. (Los prototipos 05 y 06 de `design-exploration/` conservan la
  fila lima original como registro.)
- Pasa el ratón por una sesión o semana: panel con la explicación, el veredicto y las barras «Used» y
  «Even pace». ⚠ junto al nombre = datos antiguos (el motivo, al pasar el ratón).
- **Casilla «Start with Windows»** (barra de estado): lanza Cronos al iniciar sesión, sin consola. Escribe la
  entrada `Cronos` en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (el lanzador `lanzar-widget.vbs`).
  El check refleja el estado real: si lo apagas en el Administrador de tareas › Inicio, o mueves la carpeta del
  repo, vuelve a salir sin marcar. Por defecto está sin marcar.
- Prototipos y capturas de la elección: `design-exploration/` (rama `experiment/ui-redesign`).

## Cómo funciona

- Cada cuenta vive en su propia carpeta de configuración de Claude Code (`CLAUDE_CONFIG_DIR`).
  El widget lee `<carpeta>/.credentials.json` y consulta el servicio de uso de Anthropic
  (`/api/oauth/usage`) y el de perfil (`/api/oauth/profile`).
- **Una carpeta propia por cuenta y `~/.claude` aparte.** `~/.claude` es la que usa tu Claude Code y cambia
  cuando haces otro login (también desde «Switch account» de Lion): si una cuenta vive ahí, desaparece al
  cambiar. Por eso cada cuenta tiene su carpeta (`~/.claude-cuenta1`…) y `~/.claude` va al final como «This PC».
  Si una cuenta está en dos carpetas, sale una sola vez, con los datos de la que los tiene y con el punto lima.
- Las cuentas con `"renovar": true` renuevan su token cuando caduca (mismo método que Claude Code,
  no documentado). La cuenta de `~/.claude` va con `false`: la renueva Claude Code al usarla.
- En las carpetas con `"renovar": true` no uses a la vez Claude Code: si los dos renuevan el token al mismo
  tiempo, uno se queda con un token inválido y hay que volver a iniciar sesión. Por lo mismo, solo se abre
  un widget a la vez.
- El nombre de cada cuenta sale de su email: la parte anterior a la @ en PROPER (`ventas@funidelia.es`
  → **Ventas**). Si dos cuentas comparten esa parte, se añade el dominio sin la terminación
  (**Ventas Funidelia**). El `alias` de `cuentas.json` solo se usa mientras no se conoce el email.
- Consulta el uso cada 60 s; si una cuenta lleva 5 min sin cambiar, pasa a una consulta cada 5 min
  y vuelve a cada minuto en cuanto cambia. Consulta al momento si se reinicia una ventana (sesión o
  semana) o si pulsas ⟳. Caché por cuenta y espera tras un 429. Si una cuenta no tiene datos,
  sale «No data — motivo»; nunca se muestra un 0 % inventado. Si la API no responde, se enseña el
  último dato con un ⚠ y el motivo. Un 0 % sin hora de reset es real: no hay ventana abierta (no has
  usado Claude en las últimas 5 h) y se indica como «no active window».

## Instalación

1. `copy cuentas.example.json cuentas.json` y ajusta alias y carpetas (sin secretos; fuera de git).
2. Inicia sesión una vez en cada cuenta extra, cada una en su carpeta (PowerShell, una línea; con `--email`
   el navegador abre el login con ese correo escrito; añade `--sso` si la cuenta entra por SSO):
   `$env:CLAUDE_CONFIG_DIR="$HOME\.claude-cuenta2"; claude auth login --email correo@dominio.com; Remove-Item Env:CLAUDE_CONFIG_DIR`
   Para comprobarlo: `$env:CLAUDE_CONFIG_DIR="$HOME\.claude-cuenta2"; claude auth status; Remove-Item Env:CLAUDE_CONFIG_DIR`
3. Abre el widget con `lanzar-widget.vbs` (sin consola) o con el acceso directo «Cronos» del escritorio (icono `cronos.ico`: un reloj de arena).

Arrastra la barra de título para moverlo; 📌 activa o desactiva «siempre encima»; ⟳ refresca; ✕ cierra.
La posición se guarda en `%LOCALAPPDATA%\ClaudeCuentasWidget`.

## Pruebas

```
python -m unittest discover -s widget
python widget/claude_cuentas.py --captura captura.png
```

## Límites conocidos

- La API no da un consumo mensual del plan, y los créditos extra (que sí da) ya no se muestran.
- El color por ritmo es una proyección lineal: al principio de una ventana exagera. Los cortes (5 / 15 / 25
  puntos) son los de Lion y la propuesta de Cronos.
- Las esquinas redondeadas dependen de Windows 11 (en Windows 10 se ve recta).
- Los servicios de uso y de renovación no son públicos: si Anthropic los cambia, las cuentas salen
  como «no disponible».
