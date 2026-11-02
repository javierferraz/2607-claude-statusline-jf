"""Cronos, widget de escritorio: consumo de varias cuentas de Claude (sesión de 5 h, semana y mensual).

Arranque sin consola:  pythonw claude_cuentas.py   (o lanzar-widget.vbs)
Captura de prueba:     python claude_cuentas.py --captura salida.png [--cuentas otro.json]
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

from formato import texto_mensual, texto_reset_semana, texto_reset_sesion  # noqa: E402
from uso import CARPETA_ESTADO, cargar_cuentas, consultar_todas  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA_CUENTAS = os.path.join(AQUI, 'cuentas.json')
RUTA_VENTANA = os.path.join(CARPETA_ESTADO, 'ventana.json')

REFRESCO_MS = 60_000
TICK_MS = 20_000
UMBRAL_ROJO = 80  # mismo umbral que src/render.ts

FONDO = '#1e1e1e'
FONDO_FILA = '#252526'
TEXTO = '#e6e6e6'
GRIS = '#9d9d9d'
BARRA_FONDO = '#3c3c3c'
VERDE = '#3fb950'
ROJO = '#f85149'
AVISO = '#d29922'
FUENTE = 'Segoe UI'


class Barra(tk.Canvas):
    ANCHO, ALTO = 90, 8

    def __init__(self, padre):
        super().__init__(padre, width=self.ANCHO, height=self.ALTO, bg=FONDO_FILA, highlightthickness=0)

    def poner(self, pct):
        self.delete('all')
        self.create_rectangle(0, 0, self.ANCHO, self.ALTO, fill=BARRA_FONDO, width=0)
        if pct is not None:
            w = max(0, min(100, pct)) * self.ANCHO / 100
            self.create_rectangle(0, 0, w, self.ALTO, fill=ROJO if pct >= UMBRAL_ROJO else VERDE, width=0)


class Widget:
    def __init__(self, ruta_cuentas, captura=None):
        self.ruta_cuentas = ruta_cuentas
        self.captura = captura
        self.datos = []
        self.cola = queue.Queue()
        self.ocupado = False

        self.raiz = tk.Tk()
        self.raiz.title('Cronos')
        self.raiz.overrideredirect(True)
        self.raiz.configure(bg=FONDO)
        pos = self._leer_ventana()
        self.encima = tk.BooleanVar(value=pos.get('encima', True))
        self.raiz.attributes('-topmost', self.encima.get())
        if 'x' in pos and not captura:
            self.raiz.geometry(f"+{pos['x']}+{pos['y']}")
        else:
            self.raiz.geometry('+60+60')

        cab = tk.Frame(self.raiz, bg=FONDO)
        cab.pack(fill='x', padx=8, pady=(6, 2))
        tit = tk.Label(cab, text='Cronos · consumo de Claude por cuenta', fg=GRIS, bg=FONDO, font=(FUENTE, 9))
        tit.pack(side='left')
        self.lbl_hora = tk.Label(cab, text='', fg=GRIS, bg=FONDO, font=(FUENTE, 8))
        self.lbl_hora.pack(side='left', padx=8)
        for texto, accion, ayuda in (('✕', self.cerrar, 'Cerrar'), ('⟳', lambda: self.refrescar(True), 'Refrescar'),
                                     ('📌', self.alternar_encima, 'Siempre encima')):
            b = tk.Label(cab, text=texto, fg=TEXTO, bg=FONDO, font=(FUENTE, 11), cursor='hand2')
            b.pack(side='right', padx=3)
            b.bind('<Button-1>', lambda _e, a=accion: a())
            if texto == '📌':
                self.btn_encima = b
        self._pintar_encima()
        for w in (cab, tit, self.lbl_hora):
            w.bind('<ButtonPress-1>', self._inicio_arrastre)
            w.bind('<B1-Motion>', self._arrastre)
            w.bind('<ButtonRelease-1>', lambda _e: self._guardar_ventana())

        self.cuerpo = tk.Frame(self.raiz, bg=FONDO)
        self.cuerpo.pack(fill='both', padx=6, pady=(0, 6))
        tk.Label(self.cuerpo, text='Cargando…', fg=GRIS, bg=FONDO, font=(FUENTE, 9)).pack(padx=10, pady=10)

        self.refrescar()
        self.raiz.after(200, self._mirar_cola)
        if not captura:
            self.raiz.after(REFRESCO_MS, self._refresco_periodico)
            self.raiz.after(TICK_MS, self._tick)

    # --- datos -------------------------------------------------------------------------
    def refrescar(self, forzar=False):
        if self.ocupado:
            return
        self.ocupado = True
        self.lbl_hora.config(text='actualizando…', fg=GRIS)

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
                self.lbl_hora.config(text=f'error: {r}', fg=AVISO)
            else:
                self.datos = r
                self.lbl_hora.config(text=f'actualizado {datetime.now():%H:%M}', fg=GRIS)
                self.pintar()
        except Exception as e:  # noqa: BLE001 - que un fallo de pintado no pare el refresco
            self.lbl_hora.config(text=f'error al pintar: {e}', fg=AVISO)
        if self.captura:
            self.raiz.after(600, self._capturar)
        else:
            self.raiz.after(200, self._mirar_cola)

    def _refresco_periodico(self):
        self.refrescar()
        self.raiz.after(REFRESCO_MS, self._refresco_periodico)

    def _tick(self):
        try:
            self.pintar()  # recalcula las cuentas atrás sin llamar a la API
        finally:
            self.raiz.after(TICK_MS, self._tick)

    # --- pintado -----------------------------------------------------------------------
    def pintar(self):
        for w in self.cuerpo.winfo_children():
            w.destroy()
        for d in self.datos:
            self._fila(d)

    def _fila(self, d):
        f = tk.Frame(self.cuerpo, bg=FONDO_FILA)
        f.pack(fill='x', pady=2)

        ident = tk.Frame(f, bg=FONDO_FILA, width=240, height=46)
        ident.pack_propagate(False)
        ident.pack(side='left', padx=(10, 6), pady=6)
        linea = tk.Frame(ident, bg=FONDO_FILA)
        linea.pack(fill='x')
        tk.Label(linea, text=d['nombre'], fg=TEXTO, bg=FONDO_FILA, font=(FUENTE, 10, 'bold')).pack(side='left')
        extra = ' · '.join(x for x in (d['org'], d['plan']) if x)
        if extra:
            tk.Label(linea, text=f'  {extra}', fg=GRIS, bg=FONDO_FILA, font=(FUENTE, 8)).pack(side='left')
        tk.Label(ident, text=d['email'] or 'email desconocido', fg=GRIS, bg=FONDO_FILA, font=(FUENTE, 8),
                 anchor='w').pack(fill='x')

        if d['estado'] != 'ok' or (d['sesion'] is None and d['semana'] is None):
            tk.Label(f, text=f"— no disponible: {d['error'] or 'sin datos'}", fg=AVISO, bg=FONDO_FILA,
                     font=(FUENTE, 9), anchor='w', width=74).pack(side='left', padx=8)
            return

        antiguo = f"dato de {datetime.fromtimestamp(d['dato_de']):%H:%M}" if d['dato_de'] else ''
        self._bloque(f, 'Sesión', d['sesion'], texto_reset_sesion, antiguo)
        self._bloque(f, 'Semana', d['semana'], texto_reset_semana, antiguo)

        m = tk.Frame(f, bg=FONDO_FILA, width=170, height=46)
        m.pack_propagate(False)
        m.pack(side='left', padx=8, pady=6)
        tk.Label(m, text='Mensual', fg=GRIS, bg=FONDO_FILA, font=(FUENTE, 9), anchor='w').pack(fill='x')
        tk.Label(m, text=texto_mensual(d['mensual']), fg=GRIS, bg=FONDO_FILA, font=(FUENTE, 8), anchor='w',
                 wraplength=165, justify='left').pack(fill='x')

        if d['error']:
            tk.Label(f, text='⚠', fg=AVISO, bg=FONDO_FILA, font=(FUENTE, 10)).pack(side='left', padx=(0, 6))
            self._ayuda(f.winfo_children()[-1], d['error'])

    def _bloque(self, padre, nombre, ventana, texto_reset, antiguo=''):
        b = tk.Frame(padre, bg=FONDO_FILA, width=210, height=46)
        b.pack_propagate(False)
        b.pack(side='left', padx=8, pady=6)
        arriba = tk.Frame(b, bg=FONDO_FILA)
        arriba.pack(fill='x')
        tk.Label(arriba, text=nombre, fg=GRIS, bg=FONDO_FILA, font=(FUENTE, 9)).pack(side='left')
        pct = ventana['pct'] if ventana else None
        tk.Label(arriba, text=f'{pct}%' if pct is not None else '—', fg=TEXTO, bg=FONDO_FILA,
                 font=(FUENTE, 12, 'bold')).pack(side='left', padx=(6, 8))
        barra = Barra(arriba)
        barra.pack(side='left', pady=(4, 0))
        barra.poner(pct)
        reset = texto_reset(ventana['reset']) if ventana else 'no disponible'
        if antiguo:
            reset = f'{antiguo} · {reset}'
        tk.Label(b, text=reset, fg=AVISO if antiguo else GRIS, bg=FONDO_FILA, font=(FUENTE, 8),
                 anchor='w').pack(fill='x')

    def _ayuda(self, w, texto):
        def mostrar(_e):
            self._tip = tk.Toplevel(w)
            self._tip.overrideredirect(True)
            self._tip.attributes('-topmost', True)
            self._tip.geometry(f'+{w.winfo_rootx() + 16}+{w.winfo_rooty() + 16}')
            tk.Label(self._tip, text=texto, fg=TEXTO, bg='#333333', font=(FUENTE, 8), padx=6, pady=3).pack()

        def ocultar(_e):
            if getattr(self, '_tip', None):
                self._tip.destroy()
                self._tip = None
        w.bind('<Enter>', mostrar)
        w.bind('<Leave>', ocultar)

    # --- ventana -----------------------------------------------------------------------
    def alternar_encima(self):
        self.encima.set(not self.encima.get())
        self.raiz.attributes('-topmost', self.encima.get())
        self._pintar_encima()
        self._guardar_ventana()

    def _pintar_encima(self):
        self.btn_encima.config(fg=TEXTO if self.encima.get() else '#555555')

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
                json.dump({'x': self.raiz.winfo_x(), 'y': self.raiz.winfo_y(), 'encima': self.encima.get()}, f)
        except OSError:
            pass

    def _capturar(self):
        from PIL import ImageGrab
        self.raiz.update()
        x, y = self.raiz.winfo_rootx(), self.raiz.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + self.raiz.winfo_width(), y + self.raiz.winfo_height()),
                       all_screens=True).save(self.captura)
        self.cerrar()

    def cerrar(self):
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
    a = p.parse_args()
    if not a.captura and not instancia_unica():
        return  # ya hay un widget abierto: dos renovarían el mismo token a la vez
    try:  # nitidez en pantallas escaladas y coordenadas reales para la captura
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 - fuera de Windows no aplica
        pass
    Widget(a.cuentas, a.captura).correr()


if __name__ == '__main__':
    main()
