"""Genera cronos.ico y cronos-20.png desde cronos-1024.png (python widget/generar-icono.py).

Un .ico con pocos tamaños se ve borroso: la barra de tareas pide 24 px al 100 %, 30 al 125 %, 36 al 150 %,
48 al 200 %... y si no hay un fotograma de ese tamaño Windows estira otro. Aquí hay uno para cada escala,
cada uno redibujado desde el original (no encadenado desde otro más pequeño) y con un toque de nitidez
en los pequeños, donde el reescalado suaviza los bordes.
"""
import io
import os
import struct

from PIL import Image, ImageFilter

AQUI = os.path.dirname(os.path.abspath(__file__))
TAMANOS = [16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 96, 128, 256]


def fotograma(origen, px):
    im = origen.resize((px, px), Image.LANCZOS)
    if px <= 48:
        im = im.filter(ImageFilter.UnsharpMask(radius=0.6, percent=70, threshold=0))
    return im


def png(im):
    b = io.BytesIO()
    im.save(b, 'PNG', optimize=True)
    return b.getvalue()


def main():
    origen = Image.open(os.path.join(AQUI, 'cronos-1024.png')).convert('RGBA')
    datos = [png(fotograma(origen, px)) for px in TAMANOS]
    cabecera = struct.pack('<HHH', 0, 1, len(TAMANOS))
    offset, entradas = 6 + 16 * len(TAMANOS), b''
    for px, d in zip(TAMANOS, datos):
        entradas += struct.pack('<BBBBHHII', px % 256, px % 256, 0, 0, 1, 32, len(d), offset)
        offset += len(d)
    with open(os.path.join(AQUI, 'cronos.ico'), 'wb') as f:
        f.write(cabecera + entradas + b''.join(datos))
    fotograma(origen, 20).save(os.path.join(AQUI, 'cronos-20.png'), optimize=True)
    print('cronos.ico:', len(TAMANOS), 'tamaños,', offset, 'bytes')


if __name__ == '__main__':
    main()
