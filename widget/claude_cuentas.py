"""Cronos, widget de escritorio: consumo de varias cuentas de Claude (sesión de 5 h, semana, créditos extra).

Estética de Roaring Lion (su DESIGN.md, paleta «Piedra»): chrome piedra, raya blanca de ritmo uniforme en
cada barra y color por ritmo. Interfaz en inglés, como Lion. Tema oscuro por defecto, claro disponible.

Arranque sin consola:  pythonw claude_cuentas.py   (o lanzar-widget.vbs)
Captura de prueba:     python claude_cuentas.py --captura salida.png [--tema claro] [--tip 1-ses] [--cuentas otro.json]
"""
import argparse
import json
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from formato import (SEMANA_MIN, SESION_MIN, a_fecha, dia_hora, ritmo, se_agota,  # noqa: E402
                     texto_reset_semana, texto_reset_sesion, tramo)
from uso import CARPETA_ESTADO, cargar_cuentas, consultar_todas  # noqa: E402

try:
    import winreg
except ImportError:  # fuera de Windows no hay arranque con la sesión
    winreg = None

AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA_CUENTAS = os.path.join(AQUI, 'cuentas.json')
RUTA_ICONO = os.path.join(AQUI, 'cronos-20.png')
RUTA_ICO = os.path.join(AQUI, 'cronos.ico')
APP_ID = 'Funidelia.Cronos'  # identidad propia en Windows: el botón de la barra usa el icono de Cronos, no el de Python
EXSTYLE, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = -20, 0x00040000, 0x00000080
RUTA_VENTANA = os.path.join(CARPETA_ESTADO, 'ventana.json')

REFRESCO_MS = 60_000
TICK_MS = 20_000
ALTO_FILA = 84
ANCHO_INTERIOR = 750  # 230 + 236 + 236 de columnas y 2 × 24 de separación
FUENTE = 'Segoe UI'

# --- paleta de Roaring Lion (src/styles/base.css y layout.css) ---------------------------------
ACENTO = '#aee659'
TRAMOS = {'ok': '#5fae6b', 'warn': '#e3a948', 'danger': '#d75928', 'low': '#6fa8d6'}
DANGER_CLARO = '#ff9a6e'


# --- arranque con la sesión de Windows --------------------------------------------------------------
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
APPROVED_KEY = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
RUN_NAME = 'Cronos'


def comando_inicio():
    """Lo que Windows ejecuta al iniciar sesión: el lanzador oculto (sin consola)."""
    wscript = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'System32', 'wscript.exe')
    return '"%s" "%s"' % (wscript, os.path.join(AQUI, 'lanzar-widget.vbs'))


def inicio_activo():
    """True si Windows lanzará Cronos al iniciar sesión: hay entrada en Run con la ruta de este widget y no
    está desactivada desde el Administrador de tareas (StartupApproved: primer byte 02 = activo, 03 = no)."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            valor, _ = winreg.QueryValueEx(k, RUN_NAME)
    except OSError:
        return False
    if os.path.normcase(valor) != os.path.normcase(comando_inicio()):
        return False  # apunta a otra carpeta (el repo se movió): marcar la casilla lo corrige
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as k:
            datos, _ = winreg.QueryValueEx(k, RUN_NAME)
        return not (datos and datos[0] % 2)
    except OSError:
        return True


def poner_inicio(activo):
    """Crea o quita la entrada de arranque y la marca de «desactivado» del Administrador de tareas."""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if activo:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, comando_inicio())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass
    try:  # sin esto, una desactivación antigua del Administrador de tareas dejaría la casilla marcada sin efecto
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_NAME)
    except OSError:
        pass


def mezcla(a, b, t):
    """Color a mezclado con b en una proporción t (0-1), como color-mix() de CSS."""
    x, y = [[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in (a, b)]
    return '#%02x%02x%02x' % tuple(round(p * (1 - t) + q * t) for p, q in zip(x, y))


_CHROME = dict(chrome='#413a34', chrome2='#524a43', chrome_ink='#f7f3ec', chrome_muted='#c6bcaf', chrome_line='#675f57')
TEMAS = {
    'oscuro': dict(_CHROME, row_bg='#413a34', row_hover=mezcla('#413a34', '#f7f3ec', .06),
                   marca=ACENTO,
                   ink='#f7f3ec', muted='#c6bcaf', line='#675f57', track='#675f57', tick='#f7f3ec',
                   warn_txt='#e3a948', warn_bg=mezcla('#413a34', '#e3a948', .12), warn_line=mezcla('#413a34', '#e3a948', .40)),
    'claro': dict(_CHROME, row_bg='#fcfaf6', row_hover='#f4f0e8', marca='#6a9f1f',
                  ink='#29231e', muted='#6e655c', line='#e5dfd6', track='#ddd6cb', tick='#29231e',
                  warn_txt='#7a4f00', warn_bg='#fbf0d6', warn_line='#e6cf94'),
}
VEREDICTO = {
    'ok': ('On pace', ACENTO), 'warn': ('Slightly ahead of an even pace', TRAMOS['warn']),
    'danger': ('Well ahead of an even pace', DANGER_CLARO), 'low': ('Well under an even pace — spare quota', TRAMOS['low']),
}


class Barra(tk.Canvas):
    """Barra de 110 × 8 con extremos redondos, relleno por tramo y raya del ritmo uniforme."""
    ANCHO, ALTO = 110, 8

    def __init__(self, padre, bg, ancho=None, alto=None):
        self.ancho, self.alto = ancho or self.ANCHO, alto or self.ALTO
        super().__init__(padre, width=self.ancho, height=self.alto, bg=bg, highlightthickness=0)

    def _capsula(self, x1, color):
        r = self.alto / 2
        if x1 < 2 * r:  # menos que un extremo redondo: tira plana
            self.create_rectangle(0, 0, x1, self.alto, fill=color, width=0)
            return
        self.create_oval(0, 0, 2 * r, self.alto, fill=color, width=0)
        self.create_oval(x1 - 2 * r, 0, x1, self.alto, fill=color, width=0)
        self.create_rectangle(r, 0, x1 - r, self.alto, fill=color, width=0)

    def poner(self, pct, color, pista, raya=None, color_raya=None):
        ultimo = (pct, color, pista, raya, color_raya)
        if ultimo == getattr(self, '_ultimo', None):
            return
        self._ultimo = ultimo
        self.delete('all')
        self._capsula(self.ancho, pista)
        if pct is not None and pct > 0:
            self._capsula(max(1, min(100, pct)) * self.ancho / 100, color)
        if raya is not None:
            x = raya * self.ancho / 100
            self.create_rectangle(x - 1, 0, x + 1, self.alto, fill=color_raya, width=0)


class Widget:
    def __init__(self, ruta_cuentas, captura=None, tema=None, tip=None):
        self.ruta_cuentas, self.captura, self.tip_demo = ruta_cuentas, captura, tip
        self.datos, self.cola, self.ocupado = [], queue.Queue(), False
        self.tip_win = self.tip_id = self.tip_cierre = None
        self.bloques = {}
        self.tramos = {'ok': 0, 'low': 0, 'warn': 0, 'danger': 0}
        self._estructura = None   # qué elementos hay en pantalla: si es la misma, solo se actualizan sus textos
        self._firma_estado = None
        self.actualizadores = []  # (id del bloque, función que actualiza su texto y su barra en su sitio)

        pos = self._leer_ventana()
        self.tema = tema or (pos.get('tema') if pos.get('tema') in TEMAS else 'oscuro')
        self.actualizado = ''

        self.raiz = tk.Tk()
        self.raiz.title('Cronos')
        try:
            self.raiz.iconbitmap(default=RUTA_ICO)
        except tk.TclError:
            pass
        self.raiz.overrideredirect(True)
        self.encima = tk.BooleanVar(value=pos.get('encima', True))
        self.raiz.attributes('-topmost', self.encima.get())
        self.raiz.geometry(f"+{pos['x']}+{pos['y']}" if 'x' in pos and not captura else '+60+60')
        try:
            self.icono = tk.PhotoImage(file=RUTA_ICONO)
        except tk.TclError:
            self.icono = None
        self.marco = tk.Frame(self.raiz, highlightthickness=1)
        self.marco.pack()
        self._montar()
        self._esquinas()
        if not captura:
            self.raiz.after(100, self._boton_barra_tareas)

        self.refrescar()
        self.raiz.after(200, self._mirar_cola)
        if not captura:
            self.raiz.after(REFRESCO_MS, self._refresco_periodico)
            self.raiz.after(TICK_MS, self._tick)

    def _boton_barra_tareas(self):
        """Botón propio en la barra de tareas (S-1076): una ventana sin marco no lo tiene.
        Se le quita el estilo de ventana de herramienta y se le da el de ventana de aplicación; Windows
        solo lo aplica al volver a mostrarla, de ahí el ocultar y mostrar."""
        try:
            import ctypes
            u32 = ctypes.windll.user32
            u32.GetParent.restype = ctypes.c_void_p
            u32.GetParent.argtypes = [ctypes.c_void_p]
            u32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            u32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
            hwnd = u32.GetParent(self.raiz.winfo_id()) or self.raiz.winfo_id()
            estilo = u32.GetWindowLongW(hwnd, EXSTYLE)
            u32.SetWindowLongW(hwnd, EXSTYLE, (estilo & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
            self.raiz.withdraw()
            self.raiz.after(30, self.raiz.deiconify)
        except Exception:  # noqa: BLE001 - sin botón en la barra, pero el widget funciona igual
            pass

    # --- estructura -------------------------------------------------------------------------
    @property
    def C(self):
        return TEMAS[self.tema]

    def _montar(self):
        """Barra de título, cuerpo y barra de estado. Se rehace entera al cambiar de tema."""
        C = self.C
        self.ocultar_tip()
        self._estructura = self._firma_estado = None
        for w in self.marco.winfo_children():
            w.destroy()
        self.marco.config(bg=C['chrome'], highlightbackground=C['chrome_line'], highlightcolor=C['chrome_line'])

        titulo = tk.Frame(self.marco, bg=C['chrome2'], height=36)
        titulo.pack(fill='x')
        titulo.pack_propagate(False)
        arrastrables = [titulo]
        if self.icono:
            arrastrables.append(tk.Label(titulo, image=self.icono, bg=C['chrome2']))
            arrastrables[-1].pack(side='left', padx=(10, 8))
        arrastrables.append(tk.Label(titulo, text='Cronos', fg=C['chrome_ink'], bg=C['chrome2'], font=(FUENTE, 10, 'bold')))
        arrastrables[-1].pack(side='left')
        self.lbl_hora = tk.Label(titulo, text=self.actualizado, fg=C['chrome_muted'], bg=C['chrome2'], font=(FUENTE, 9))
        self.lbl_hora.pack(side='left', padx=10)
        arrastrables.append(self.lbl_hora)
        for texto, accion, rojo in (('✕', self.cerrar, True), ('⟳', lambda: self.refrescar(True), False),
                                    ('📌', self.alternar_encima, False),
                                    ('☀' if self.tema == 'oscuro' else '🌙', self.alternar_tema, False)):
            b = tk.Label(titulo, text=texto, fg=C['chrome_muted'], bg=C['chrome2'], font=(FUENTE, 11), width=3, cursor='hand2')
            b.pack(side='right', padx=1, pady=5)
            self._boton(b, accion, rojo)
            if texto == '📌':
                self.btn_encima = b
        self._pintar_encima()
        for w in arrastrables:
            w.bind('<ButtonPress-1>', self._inicio_arrastre)
            w.bind('<B1-Motion>', self._arrastre)
            w.bind('<ButtonRelease-1>', lambda _e: self._guardar_ventana())

        self.cuerpo = tk.Frame(self.marco, bg=C['row_bg'])
        self.cuerpo.pack(fill='x')
        self.estado = tk.Frame(self.marco, bg=C['chrome2'], height=24)
        self.estado.pack(fill='x')
        self.estado.pack_propagate(False)
        if self.datos:
            self.pintar()
        else:
            tk.Label(self.cuerpo, text='Loading…', fg=C['muted'], bg=C['row_bg'], font=(FUENTE, 10), height=3, width=60).pack()
            self._pintar_estado()  # la casilla de arranque debe estar aunque aún no haya datos

    def _boton(self, b, accion, rojo):
        C = self.C
        b.bind('<Button-1>', lambda _e: accion())
        b.bind('<Enter>', lambda _e: b.config(bg=TRAMOS['danger'] if rojo else C['chrome_line'],
                                              fg='#ffffff' if rojo else C['chrome_ink']))
        b.bind('<Leave>', lambda _e: (b.config(bg=C['chrome2'], fg=C['chrome_muted']), self._pintar_encima()))

    def _esquinas(self):
        """Esquinas redondeadas de Windows 11 (best effort); en Windows 10 se queda recta."""
        try:
            import ctypes
            self.raiz.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.raiz.winfo_id()) or self.raiz.winfo_id()
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)
        except Exception:  # noqa: BLE001
            pass

    # --- datos ------------------------------------------------------------------------------
    def refrescar(self, forzar=False):
        if self.ocupado:
            return
        self.ocupado = True
        if forzar:  # en las consultas automáticas el texto no cambia: así no parpadea cada minuto
            self.lbl_hora.config(text='updating…')

        def trabajo():
            try:
                self.cola.put(consultar_todas(cargar_cuentas(self.ruta_cuentas), forzar=forzar))
            except Exception as e:  # noqa: BLE001 - se enseña en la ventana
                self.cola.put(e)
        # No es daemon: si se cierra la ventana mientras renueva un token, la escritura termina.
        threading.Thread(target=trabajo).start()

    def _mirar_cola(self):
        try:
            r = self.cola.get_nowait()
        except queue.Empty:
            self.raiz.after(200, self._mirar_cola)
            return
        self.ocupado = False
        try:
            if isinstance(r, Exception):
                self.lbl_hora.config(text=f'error: {r}', fg=TRAMOS['warn'])
            else:
                self.datos = r
                self.actualizado = f'updated {datetime.now():%H:%M}'
                self.lbl_hora.config(text=self.actualizado, fg=self.C['chrome_muted'])
                self.pintar()
        except Exception as e:  # noqa: BLE001 - que un fallo de pintado no pare el refresco
            self.lbl_hora.config(text=f'paint error: {e}', fg=TRAMOS['warn'])
        if self.captura:
            self.raiz.after(500, self._preparar_captura)
        else:
            self.raiz.after(200, self._mirar_cola)

    def _refresco_periodico(self):
        self.refrescar()
        self.raiz.after(REFRESCO_MS, self._refresco_periodico)

    def _tick(self):
        try:
            if self.tip_win is None:  # no repintar con un panel abierto: se cerraría al instante
                self.pintar()  # recalcula cuentas atrás y raya de ritmo sin llamar a la API
        finally:
            self.raiz.after(TICK_MS, self._tick)

    # --- pintado ----------------------------------------------------------------------------
    @staticmethod
    def _forma(d):
        """Lo que decide qué elementos se crean para una cuenta (no sus cifras): si no cambia, no se reconstruye."""
        con_datos = d['estado'] == 'ok' and bool(d['sesion'] or d['semana'])
        return (d['nombre'], d['email'], bool(d.get('esta')), (d['plan'] or '').split(' · ')[-1], con_datos,
                d['error'], d['dato_de'], d['sesion'] is None, d['semana'] is None)

    def pintar(self):
        C = self.C
        ahora = datetime.now()
        estructura = (self.tema, tuple(self._forma(d) for d in self.datos))
        if estructura == self._estructura:
            # Mismos elementos: solo cambian cifras, barras y cuentas atrás. Se actualizan en su sitio, sin crear
            # ni destruir nada (reconstruir ~60 elementos de Windows cada minuto se notaba como un parpadeo), y
            # el panel emergente abierto no se cierra.
            self.tramos = {'ok': 0, 'low': 0, 'warn': 0, 'danger': 0}
            for id_, actualizar in self.actualizadores:
                n, clave = id_.split('-')
                d = self.datos[int(n)]
                actualizar(d['sesion' if clave == 'ses' else 'semana'], d, ahora)
            self._pintar_estado()
            return
        self._estructura = estructura
        self.ocultar_tip()
        self.bloques, self.actualizadores = {}, []
        viejo = self.cuerpo
        self.cuerpo = tk.Frame(self.marco, bg=C['row_bg'])  # se monta aparte y se cambia de golpe, sin ventana vacía
        self.tramos = {'ok': 0, 'low': 0, 'warn': 0, 'danger': 0}
        for i, d in enumerate(self.datos):
            if i:
                tk.Frame(self.cuerpo, height=1, bg=C['line']).pack(fill='x')
            self._fila(i, d, ahora)
        self.cuerpo.pack(fill='x', before=self.estado)
        viejo.destroy()
        self._pintar_estado()

    def _fila(self, i, d, ahora):
        C = self.C
        bg = C['row_bg']
        fila = tk.Frame(self.cuerpo, bg=bg)
        fila.pack(fill='x')
        dentro = tk.Frame(fila, bg=bg, height=ALTO_FILA, width=ANCHO_INTERIOR)
        dentro.pack(fill='x', padx=16)
        dentro.pack_propagate(False)

        ident = tk.Frame(dentro, bg=bg, width=230, height=52)
        ident.pack_propagate(False)
        ident.pack(side='left', padx=(0, 24))
        linea = tk.Frame(ident, bg=bg)
        linea.pack(anchor='w', fill='x')
        tk.Label(linea, text=d['nombre'], fg=C['ink'], bg=bg, font=(FUENTE, 10, 'bold')).pack(side='left')
        if d.get('esta'):  # la cuenta con la que se usa Claude Code en este PC: un punto tras el nombre, sin tocar el fondo
            punto = tk.Label(linea, text=' ●', fg=C['marca'], bg=bg, font=(FUENTE, 7), cursor='question_arrow')
            punto.pack(side='left')
            self._ayuda_simple(punto, 'The account Claude Code is signed in with on this PC')
        con_datos = d['estado'] == 'ok' and bool(d['sesion'] or d['semana'])
        if con_datos and d['error']:  # datos antiguos: el motivo va en la ayuda del aviso
            aviso = tk.Label(linea, text=' ⚠', fg=C['warn_txt'], bg=bg, font=(FUENTE, 10), cursor='question_arrow')
            aviso.pack(side='left')
            self._ayuda_simple(aviso, self._texto_antiguo(d))
        tier = (d['plan'] or '').split(' · ')[-1]  # «Team · Max 5x» -> «Max 5x»: lo único que interesa del plan
        if tier:
            tk.Label(linea, text='  ' + tier, fg=C['muted'], bg=bg, font=(FUENTE, 8)).pack(side='left')
        tk.Label(ident, text=d['email'] or 'email unknown', fg=C['muted'], bg=bg, font=(FUENTE, 9), anchor='w').pack(anchor='w', pady=(6, 0))

        if not con_datos:
            caja = tk.Frame(dentro, bg=C['warn_bg'], highlightthickness=1, highlightbackground=C['warn_line'])
            caja._fijo = True
            caja.pack(side='left', fill='x', expand=True, pady=22)
            mensaje = tk.Label(caja, text=f"⚠ No data — {d['error'] or 'no data yet'}", fg=C['warn_txt'], bg=C['warn_bg'],
                               font=(FUENTE, 10), anchor='w')
            mensaje._fijo = True
            mensaje.pack(fill='x', padx=10, pady=5)
        else:
            self._bloque(dentro, bg, 'Session', d['sesion'], SESION_MIN, f'{i}-ses', d, ahora)
            self._bloque(dentro, bg, 'Week', d['semana'], SEMANA_MIN, f'{i}-sem', d, ahora)

        self._ligar_hover(fila)

    def _bloque(self, padre, bg, titulo, v, span, id_, d, ahora):
        C = self.C
        f = tk.Frame(padre, bg=bg, width=236, height=52)
        f.pack_propagate(False)
        f.pack(side='left', padx=(0, 24))
        arriba = tk.Frame(f, bg=bg)
        arriba.pack(anchor='w')
        tk.Label(arriba, text=titulo, fg=C['muted'], bg=bg, font=(FUENTE, 10)).pack(side='left')
        if v is None:
            tk.Label(arriba, text='—', fg=C['ink'], bg=bg, font=(FUENTE, 14, 'bold')).pack(side='left', padx=8)
            tk.Label(f, text='not available', fg=C['muted'], bg=bg, font=(FUENTE, 9), anchor='w').pack(anchor='w', pady=(6, 0))
            return
        lbl_pct = tk.Label(arriba, text='', bg=bg, font=(FUENTE, 14, 'bold'), width=4, anchor='w')
        lbl_pct.pack(side='left', padx=(4, 4))
        barra = Barra(arriba, bg)
        barra.pack(side='left', pady=(5, 0))
        lbl_sub = tk.Label(f, text='', bg=bg, font=(FUENTE, 9), anchor='w')
        lbl_sub.pack(anchor='w', pady=(6, 0))

        def actualizar(v, d, ahora):
            pct = v['pct']
            raya = ritmo(v['reset'], span, ahora)
            nivel = tramo(pct, raya)
            self.tramos[nivel] += 1
            agota = se_agota(pct, v['reset'], span, ahora)
            limite = pct >= 100
            lbl_pct.config(text=f'{pct}%', fg=TRAMOS['danger'] if limite else C['ink'])
            barra.poner(pct, TRAMOS[nivel], C['track'], raya, C['tick'])
            if agota:
                sub, color = f'at this pace, out {dia_hora(agota)}', TRAMOS['danger']
            else:
                texto = texto_reset_sesion if span == SESION_MIN else texto_reset_semana
                sub = texto(v['reset'], ahora) or ('no active window' if pct == 0 else 'no reset time')
                color = TRAMOS['danger'] if limite else C['muted']
            if lbl_sub.cget('text') != sub or lbl_sub.cget('fg') != color:
                lbl_sub.config(text=sub, fg=color)
            self.bloques[id_] = (f, dict(pct=pct, span=span, raya=raya, nivel=nivel, agota=agota, v=v, antiguo=d, ahora=ahora))
        actualizar(v, d, ahora)
        self.actualizadores.append((id_, actualizar))
        self._ligar_tip(f, id_)

    def _pintar_estado(self):
        C = self.C
        con = sum(1 for d in self.datos if d['estado'] == 'ok' and (d['sesion'] or d['semana']))
        antiguos = sum(1 for d in self.datos if d['estado'] == 'ok' and (d['sesion'] or d['semana']) and d['error'])
        activo = inicio_activo() if winreg is not None else False
        firma = (self.tema, len(self.datos), con, antiguos, self.tramos['danger'], activo)
        if firma == self._firma_estado:
            return
        self._firma_estado = firma
        viejo = self.estado
        self.estado = tk.Frame(self.marco, bg=C['chrome2'], height=24)  # se monta aparte y se cambia de golpe
        self.estado.pack_propagate(False)
        self.estado.pack(fill='x')

        def etiqueta(texto, color=None, negrita=False, lado='left', padx=(0, 12)):
            tk.Label(self.estado, text=texto, fg=color or C['chrome_muted'], bg=C['chrome2'],
                     font=(FUENTE, 8, 'bold' if negrita else 'normal')).pack(side=lado, padx=padx)
        if self.datos:
            etiqueta(f'{len(self.datos)} accounts', C['chrome_ink'], True, padx=(12, 12))
            etiqueta(f'{con} with data')
            if self.tramos['danger']:
                etiqueta(f"{self.tramos['danger']} over pace", DANGER_CLARO)
            if antiguos:
                etiqueta(f'{antiguos} stale', TRAMOS['warn'])
        if winreg is not None:
            casilla = tk.Label(self.estado, text=('☑' if activo else '☐') + ' Start with Windows',
                               fg=C['chrome_ink'] if activo else C['chrome_muted'], bg=C['chrome2'],
                               font=(FUENTE, 8), cursor='hand2')
            casilla.pack(side='right', padx=(0, 12))
            casilla.bind('<Button-1>', lambda _e: self.alternar_inicio())
            self._ayuda_simple(casilla, 'Launch Cronos when you sign in to Windows. It can also be turned off '
                                        'in Task Manager › Startup apps; this box shows the real state.')
        etiqueta('┃ even pace', lado='right')
        for nombre, clave in (('over', 'danger'), ('ahead', 'warn'), ('on pace', 'ok'), ('spare', 'low')):
            etiqueta(f'● {nombre}', TRAMOS[clave], lado='right', padx=(0, 10))
        viejo.destroy()

    # --- hover de fila y panel emergente (el de RAM de Lion) ----------------------------------
    def _ligar_hover(self, fila):
        def recolorear(w, color):
            if getattr(w, '_fijo', False):
                return
            try:
                w.config(bg=color)
            except tk.TclError:
                pass
            for h in w.winfo_children():
                recolorear(h, color)

        def dentro(_e=None):
            recolorear(fila, self.C['row_hover'])

        def fuera(_e=None):
            x, y = self.raiz.winfo_pointerxy()
            w = self.raiz.winfo_containing(x, y)
            if w is not None and str(w).startswith(str(fila)):
                return  # solo cambió de hijo dentro de la misma fila
            recolorear(fila, self.C['row_bg'])

        def ligar(w):
            w.bind('<Enter>', dentro, add='+')
            w.bind('<Leave>', fuera, add='+')
            for h in w.winfo_children():
                ligar(h)
        ligar(fila)

    def _ligar_tip(self, f, id_):
        def entra(_e=None):
            if self.tip_cierre:
                self.raiz.after_cancel(self.tip_cierre)
                self.tip_cierre = None
            if self.tip_id != id_:
                self.raiz.after(120, lambda: self._abrir_tip(id_, comprobar_puntero=True))

        def sale(_e=None):
            if self.tip_cierre:
                self.raiz.after_cancel(self.tip_cierre)
            self.tip_cierre = self.raiz.after(90, lambda: self._cerrar_si_fuera(f))

        def ligar(w):
            w.bind('<Enter>', entra, add='+')
            w.bind('<Leave>', sale, add='+')
            for h in w.winfo_children():
                ligar(h)
        ligar(f)

    def _cerrar_si_fuera(self, f):
        self.tip_cierre = None
        x, y = self.raiz.winfo_pointerxy()
        w = self.raiz.winfo_containing(x, y)
        try:
            if w is not None and str(w).startswith(str(f)):
                return
        except tk.TclError:
            pass
        self.ocultar_tip()

    def _ayuda_simple(self, w, texto):
        def mostrar(_e):
            self.ocultar_tip()
            self.tip_win = t = tk.Toplevel(self.raiz)
            t.overrideredirect(True)
            t.attributes('-topmost', True)
            t.geometry(f'+{w.winfo_rootx() + 12}+{w.winfo_rooty() + 24}')
            tk.Label(t, text=texto, fg=self.C['chrome_ink'], bg=self.C['chrome'], font=(FUENTE, 9), padx=8, pady=5,
                     wraplength=320, justify='left', highlightthickness=1, highlightbackground=self.C['chrome_line']).pack()
        w.bind('<Enter>', mostrar)
        w.bind('<Leave>', lambda _e: self.ocultar_tip())

    @staticmethod
    def _texto_antiguo(d):
        dato = f"Data from {datetime.fromtimestamp(d['dato_de']):%H:%M} — " if d.get('dato_de') else ''
        return f"{dato}{d['error']}"

    def _abrir_tip(self, id_, comprobar_puntero=False):
        if id_ not in self.bloques:
            return
        f, t = self.bloques[id_]
        try:
            if comprobar_puntero:
                x, y = self.raiz.winfo_pointerxy()
                w = self.raiz.winfo_containing(x, y)
                if w is None or not str(w).startswith(str(f)):
                    return
        except tk.TclError:
            return
        self.ocultar_tip()
        C = self.C
        ch, ink, mu, li = C['chrome'], C['chrome_ink'], C['chrome_muted'], C['chrome_line']
        self.tip_win = win = tk.Toplevel(self.raiz)
        self.tip_id = id_
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        marco = tk.Frame(win, bg=ch, highlightthickness=1, highlightbackground=li)
        marco.pack()
        cuerpo = tk.Frame(marco, bg=ch)
        cuerpo.pack(padx=14, pady=12)
        cabeza = tk.Frame(cuerpo, bg=ch)
        cabeza.pack(fill='x')
        tk.Label(cabeza, text=f"{t['pct']}%", fg=ink, bg=ch, font=(FUENTE, 15, 'bold')).pack(side='left')
        tk.Label(cabeza, text=f"of the {'5 h session' if t['span'] == SESION_MIN else 'week'}", fg=mu, bg=ch,
                 font=(FUENTE, 9)).pack(side='left', padx=6, pady=(5, 0))

        raya, pct = t['raya'], t['pct']
        if raya is None:
            texto = 'There is no reset time, so there is no even-pace mark; the fixed tiers (50 % / 80 %) apply.'
        else:
            dif = round(pct - raya)
            donde = 'right on it' if dif == 0 else f'{dif} points ahead of it' if dif > 0 else f'{-dif} points under it'
            texto = f'An even pace to reach 100% at the reset would be at {round(raya)}% by now: you are {donde}.'
        if t['agota']:
            reset = a_fecha(t['v']['reset'])
            texto += f" At this pace it runs out {dia_hora(t['agota'])}, before it resets {dia_hora(reset) if reset else 'the reset'}."
        if t['antiguo'].get('error'):
            texto += f" {self._texto_antiguo(t['antiguo'])}."
        tk.Label(cuerpo, text=texto, fg=mu, bg=ch, font=(FUENTE, 9), wraplength=312, justify='left', anchor='w').pack(fill='x', pady=(4, 8))
        tk.Frame(cuerpo, bg=li, height=1).pack(fill='x', pady=(0, 10))

        titulo, color = VEREDICTO[t['nivel']]
        ver = tk.Frame(cuerpo, bg=mezcla(ch, color, .12))
        ver.pack(fill='x', pady=(0, 12))
        tk.Frame(ver, bg=color, width=3).pack(side='left', fill='y')
        txt = tk.Frame(ver, bg=ver['bg'])
        txt.pack(side='left', padx=10, pady=6, fill='x')
        tk.Label(txt, text=titulo, fg=color, bg=ver['bg'], font=(FUENTE, 9, 'bold'), anchor='w').pack(anchor='w')
        resets = (texto_reset_sesion if t['span'] == SESION_MIN else texto_reset_semana)(t['v']['reset'], t['ahora'])
        tk.Label(txt, text=resets, fg=ink, bg=ver['bg'], font=(FUENTE, 9), anchor='w').pack(anchor='w')

        tk.Label(cuerpo, text='THIS WINDOW', fg=mu, bg=ch, font=(FUENTE, 8), anchor='w').pack(fill='x', pady=(0, 3))
        for nombre, valor in (('Used', pct), ('Even pace', raya)):
            fila = tk.Frame(cuerpo, bg=ch)
            fila.pack(fill='x', pady=2)
            tk.Label(fila, text=nombre, fg=ink, bg=ch, font=(FUENTE, 9), width=10, anchor='w').pack(side='left')
            b = Barra(fila, ch, ancho=150, alto=6)
            b.pack(side='left', padx=8)
            b.poner(valor, mu, li)
            tk.Label(fila, text='—' if valor is None else f'{round(valor)}%', fg=ink, bg=ch, font=(FUENTE, 9), width=5,
                     anchor='e').pack(side='left')

        win.update_idletasks()
        x, y = f.winfo_rootx() - 6, f.winfo_rooty() + f.winfo_height() + 8
        ancho, alto = win.winfo_reqwidth(), win.winfo_reqheight()
        if y + alto > win.winfo_screenheight() - 40:
            y = f.winfo_rooty() - alto - 8
        x = max(0, min(x, win.winfo_screenwidth() - ancho - 8))
        win.geometry(f'+{x}+{max(0, y)}')

    def ocultar_tip(self):
        if self.tip_win is not None:
            try:
                self.tip_win.destroy()
            except tk.TclError:
                pass
        self.tip_win = self.tip_id = None

    # --- ventana ----------------------------------------------------------------------------
    def alternar_tema(self):
        self.tema = 'claro' if self.tema == 'oscuro' else 'oscuro'
        self._montar()
        self._guardar_ventana()

    def alternar_inicio(self):
        try:
            poner_inicio(not inicio_activo())
        except OSError as e:
            self.lbl_hora.config(text=f'startup error: {e}', fg=TRAMOS['warn'])
        self._pintar_estado()

    def alternar_encima(self):
        self.encima.set(not self.encima.get())
        self.raiz.attributes('-topmost', self.encima.get())
        self._pintar_encima()
        self._guardar_ventana()

    def _pintar_encima(self):
        try:
            self.btn_encima.config(fg=self.C['chrome_ink'] if self.encima.get() else '#8d857b')
        except (AttributeError, tk.TclError):
            pass

    def _inicio_arrastre(self, e):
        self._dx, self._dy = e.x_root - self.raiz.winfo_x(), e.y_root - self.raiz.winfo_y()

    def _arrastre(self, e):
        self.raiz.geometry(f'+{e.x_root - self._dx}+{e.y_root - self._dy}')

    def _leer_ventana(self):
        try:
            with open(RUTA_VENTANA, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _guardar_ventana(self):
        if self.captura:
            return
        try:
            os.makedirs(CARPETA_ESTADO, exist_ok=True)
            with open(RUTA_VENTANA, 'w', encoding='utf-8') as f:
                json.dump({'x': self.raiz.winfo_x(), 'y': self.raiz.winfo_y(), 'encima': self.encima.get(),
                           'tema': self.tema}, f)
        except OSError:
            pass

    def _preparar_captura(self):
        if self.tip_demo and self.tip_demo in self.bloques and self.tip_win is None:
            self.raiz.update()
            self._abrir_tip(self.tip_demo)
            self.raiz.after(500, self._capturar)
        else:
            self._capturar()

    def _capturar(self):
        from PIL import ImageGrab
        self.raiz.update()
        x0, y0 = self.raiz.winfo_rootx() - 1, self.raiz.winfo_rooty() - 1
        x1, y1 = x0 + self.raiz.winfo_width() + 2, y0 + self.raiz.winfo_height() + 2
        if self.tip_win is not None:
            t = self.tip_win
            x0, y0 = min(x0, t.winfo_rootx()), min(y0, t.winfo_rooty())
            x1, y1 = max(x1, t.winfo_rootx() + t.winfo_width()), max(y1, t.winfo_rooty() + t.winfo_height())
        ImageGrab.grab(bbox=(x0, y0, x1, y1), all_screens=True).save(self.captura)
        self.cerrar()

    def cerrar(self):
        self.ocultar_tip()
        self._guardar_ventana()
        self.raiz.destroy()

    def correr(self):
        self.raiz.mainloop()


def instancia_unica():
    """Mutex con nombre de Windows; False si ya hay otro widget abierto."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        global _MUTEX  # se mantiene vivo mientras dure el proceso
        _MUTEX = k32.CreateMutexW(None, False, r'Local\ClaudeCuentasWidget')
        return k32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001 - fuera de Windows no aplica
        return True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cuentas', default=RUTA_CUENTAS, help='fichero de cuentas (por defecto widget/cuentas.json)')
    p.add_argument('--captura', help='guarda una captura PNG de la ventana y sale')
    p.add_argument('--tema', choices=sorted(TEMAS), help='tema (por defecto el último usado; oscuro la primera vez)')
    p.add_argument('--tip', help='con --captura, abre el panel de un bloque (p. ej. 0-ses, 1-sem)')
    a = p.parse_args()
    if not a.captura and not instancia_unica():
        return  # ya hay un widget abierto: dos renovarían el mismo token a la vez
    try:  # nitidez en pantallas escaladas y coordenadas reales para la captura
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 - fuera de Windows no aplica
        pass
    try:  # antes de crear la ventana: así el botón de la barra de tareas es de Cronos
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001 - fuera de Windows no aplica
        pass
    Widget(a.cuentas, a.captura, a.tema, a.tip).correr()


if __name__ == '__main__':
    main()
