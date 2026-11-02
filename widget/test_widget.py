"""Pruebas del widget sin red: la API se sustituye por respuestas simuladas.

python -m unittest discover -s widget
"""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uso  # noqa: E402
from formato import cuenta_atras, etiqueta_plan, nombres_amistosos, texto_mensual, texto_reset_semana, texto_reset_sesion  # noqa: E402

USO_REAL = {  # forma de la respuesta real de /api/oauth/usage (2026-11-02), recortada
    'five_hour': {'utilization': 10.0, 'resets_at': '2026-11-02T12:20:00.717029+00:00'},
    'seven_day': {'utilization': 12.0, 'resets_at': '2026-11-07T15:00:00.717049+00:00'},
    'extra_usage': {'is_enabled': False, 'monthly_limit': None, 'used_credits': None, 'currency': None,
                    'decimal_places': None},
}


def leer(ruta):
    with open(ruta, encoding='utf-8') as f:
        return f.read()


def crear_carpeta(base, nombre, token, email, caduca_en_s=3600):
    d = os.path.join(base, nombre)
    os.makedirs(d)
    with open(os.path.join(d, '.credentials.json'), 'w', encoding='utf-8') as f:
        json.dump({'claudeAiOauth': {'accessToken': token, 'refreshToken': 'r-' + token,
                                     'expiresAt': int((time.time() + caduca_en_s) * 1000),
                                     'scopes': ['user:profile'], 'subscriptionType': 'team',
                                     'rateLimitTier': 'default_claude_max_5x'}}, f)
    with open(os.path.join(d, '.claude.json'), 'w', encoding='utf-8') as f:
        json.dump({'oauthAccount': {'emailAddress': email, 'organizationName': 'Org ' + nombre}}, f)
    return d


class Formato(unittest.TestCase):
    def test_cuenta_atras(self):
        ahora = datetime(2026, 11, 2, 11, 6)
        self.assertEqual(cuenta_atras(datetime(2026, 11, 2, 13, 20).astimezone().isoformat(), ahora), '2 h 14 min')
        self.assertEqual(cuenta_atras(datetime(2026, 11, 7, 16, 0).astimezone().isoformat(), ahora), '5 d 4 h')
        self.assertEqual(cuenta_atras(datetime(2026, 11, 2, 11, 30).astimezone().isoformat(), ahora), '24 min')
        self.assertEqual(cuenta_atras(datetime(2026, 11, 2, 10, 0).astimezone().isoformat(), ahora), '')
        self.assertEqual(cuenta_atras(None, ahora), '')

    def test_textos_reset_como_la_captura(self):
        ahora = datetime(2026, 11, 2, 11, 6)
        self.assertEqual(texto_reset_sesion(datetime(2026, 11, 2, 13, 20).astimezone().isoformat(), ahora),
                         'reset en 2 h 14 min, a las 13:20')
        self.assertEqual(texto_reset_semana(datetime(2026, 11, 7, 16, 0).astimezone().isoformat(), ahora),
                         'reset en 5 d 4 h, sáb 16:00')

    def test_epoch_y_utc(self):
        d = datetime(2026, 11, 2, 13, 20)
        self.assertEqual(texto_reset_sesion(d.timestamp(), d - timedelta(minutes=5)), 'reset en 5 min, a las 13:20')
        self.assertTrue(texto_reset_sesion('2026-11-02T12:20:00+00:00').endswith(
            datetime.fromisoformat('2026-11-02T12:20:00+00:00').astimezone().strftime('%H:%M')))

    def test_nombres_amistosos(self):
        self.assertEqual(nombres_amistosos(['ventas@funidelia.es']), ['Ventas'])
        self.assertEqual(nombres_amistosos(['javier.ferraz@x.com', None]), ['Javier.Ferraz', None])
        # dos cuentas con el mismo id: id + dominio sin terminación
        self.assertEqual(nombres_amistosos(['ventas@funidelia.es', 'VENTAS@otra.com', 'ana@funidelia.es']),
                         ['Ventas Funidelia', 'Ventas Otra', 'Ana'])
        # si aun así chocan (mismo id y mismo dominio base), el email completo
        self.assertEqual(nombres_amistosos(['a@x.es', 'a@x.com']), ['a@x.es', 'a@x.com'])

    def test_plan_y_mensual(self):
        self.assertEqual(etiqueta_plan('team', 'default_claude_max_5x'), 'Team · Max 5x')
        self.assertEqual(etiqueta_plan('pro', None), 'Pro')
        self.assertEqual(texto_mensual(None), 'no disponible')
        self.assertEqual(texto_mensual({'activo': False}), 'no disponible (créditos extra desactivados)')
        self.assertEqual(texto_mensual({'activo': True, 'usado': 3.5, 'limite': 50.0, 'moneda': 'USD'}),
                         '3.50 / 50.00 USD')


class Cuentas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_cada_cuenta_con_sus_datos(self):
        """CA2: dos cuentas, cada una con su token, no se mezclan."""
        a = crear_carpeta(self.base, 'a', 'tok-a', 'a@x.es')
        b = crear_carpeta(self.base, 'b', 'tok-b', 'b@x.es')
        usos = {'tok-a': 10.0, 'tok-b': 77.0}

        def http(url, token=None, cuerpo=None):
            if url == uso.URL_PERFIL:
                return {'account': {'email': token + '@perfil'}, 'organization': {'name': 'Org'}}
            u = json.loads(json.dumps(USO_REAL))
            u['five_hour']['utilization'] = usos[token]
            return u
        cache = {}
        ra = uso.consultar_cuenta({'alias': 'A', 'dir': a}, cache, http)
        rb = uso.consultar_cuenta({'alias': 'B', 'dir': b}, cache, http)
        self.assertEqual((ra['email'], ra['sesion']['pct']), ('tok-a@perfil', 10))
        self.assertEqual((rb['email'], rb['sesion']['pct']), ('tok-b@perfil', 77))
        self.assertEqual(ra['semana']['pct'], 12)
        self.assertEqual(ra['plan'], 'Team · Max 5x')
        self.assertFalse(ra['mensual']['activo'])

    def test_sin_credenciales(self):
        """CA3: carpeta sin login -> no disponible, sin números."""
        r = uso.consultar_cuenta({'alias': 'X', 'dir': os.path.join(self.base, 'no-existe')}, {},
                                 lambda *a, **k: self.fail('no debe llamar a la API'))
        self.assertEqual(r['estado'], 'sin_credenciales')
        self.assertIsNone(r['sesion'])
        self.assertIsNone(r['semana'])

    def test_caducado_sin_renovar(self):
        d = crear_carpeta(self.base, 'c', 'tok-c', 'c@x.es', caduca_en_s=-60)
        r = uso.consultar_cuenta({'alias': 'C', 'dir': d, 'renovar': False}, {},
                                 lambda *a, **k: self.fail('no debe llamar a la API'))
        self.assertEqual(r['estado'], 'token_caducado')
        self.assertIsNone(r['sesion'])

    def test_renovacion_fallida(self):
        """CA3: si la renovación falla, la cuenta sale caducada y el fichero queda igual."""
        d = crear_carpeta(self.base, 'd', 'tok-d', 'd@x.es', caduca_en_s=-60)
        antes = leer(os.path.join(d, '.credentials.json'))

        def http(url, token=None, cuerpo=None):
            raise uso.ErrorHttp(400)
        r = uso.consultar_cuenta({'alias': 'D', 'dir': d, 'renovar': True}, {}, http)
        self.assertEqual(r['estado'], 'token_caducado')
        self.assertIsNone(r['sesion'])
        self.assertEqual(leer(os.path.join(d, '.credentials.json')), antes)

    def test_renovacion_correcta_guarda_token(self):
        d = crear_carpeta(self.base, 'e', 'tok-viejo', 'e@x.es', caduca_en_s=-60)
        llamadas = []

        def http(url, token=None, cuerpo=None):
            llamadas.append((url, token, cuerpo))
            if url == uso.URL_TOKEN:
                return {'access_token': 'tok-nuevo', 'refresh_token': 'r-nuevo', 'expires_in': 28800}
            if url == uso.URL_PERFIL:
                return {'account': {'email': 'e@x.es'}, 'organization': {'name': 'Org'}}
            return USO_REAL
        r = uso.consultar_cuenta({'alias': 'E', 'dir': d, 'renovar': True}, {}, http)
        self.assertEqual(r['estado'], 'ok')
        self.assertEqual(llamadas[0][2]['grant_type'], 'refresh_token')
        self.assertEqual(llamadas[0][2]['refresh_token'], 'r-tok-viejo')
        self.assertEqual(llamadas[1][1], 'tok-nuevo')
        oauth = json.loads(leer(os.path.join(d, '.credentials.json')))['claudeAiOauth']
        self.assertEqual((oauth['accessToken'], oauth['refreshToken']), ('tok-nuevo', 'r-nuevo'))
        self.assertEqual(oauth['subscriptionType'], 'team')  # conserva el resto de campos

    def test_429_usa_cache_y_espera(self):
        d = crear_carpeta(self.base, 'f', 'tok-f', 'f@x.es')
        cache = {}
        ok = lambda url, token=None, cuerpo=None: USO_REAL  # noqa: E731
        t0 = time.time()
        uso.consultar_cuenta({'alias': 'F', 'dir': d}, cache, ok, ahora=t0)

        def limitado(url, token=None, cuerpo=None):
            if url == uso.URL_USO:
                raise uso.ErrorHttp(429, '120')
            return {}
        r = uso.consultar_cuenta({'alias': 'F', 'dir': d}, cache, limitado, ahora=t0 + 200)
        self.assertEqual(r['sesion']['pct'], 10)  # dato anterior, marcado como antiguo
        self.assertIsNotNone(r['dato_de'])
        self.assertIn('429', r['error'])
        self.assertAlmostEqual(cache[d]['espera_hasta'], t0 + 320)

    def test_api_caida_sin_cache(self):
        d = crear_carpeta(self.base, 'g', 'tok-g', 'g@x.es')

        def caida(url, token=None, cuerpo=None):
            raise OSError('sin red')
        r = uso.consultar_cuenta({'alias': 'G', 'dir': d}, {}, caida)
        self.assertIsNone(r['sesion'])
        self.assertIn('sin conexión', r['error'])
        self.assertEqual(r['email'], 'g@x.es')  # identidad local de .claude.json


    def test_renovacion_fallo_pasajero_sin_caducar(self):
        """Un fallo de red al renovar con el token aún válido no marca la cuenta como caducada."""
        d = crear_carpeta(self.base, 'h', 'tok-h', 'h@x.es', caduca_en_s=120)
        cache = {}

        def http(url, token=None, cuerpo=None):
            if url == uso.URL_TOKEN:
                raise OSError('sin red')
            return USO_REAL if url == uso.URL_USO else {}
        r = uso.consultar_cuenta({'alias': 'H', 'dir': d, 'renovar': True}, cache, http)
        self.assertEqual(r['estado'], 'ok')
        self.assertEqual(r['sesion']['pct'], 10)
        self.assertGreater(cache[d]['renovar_espera_hasta'], time.time())

    def test_fallo_inesperado_aislado(self):
        """Un .credentials.json raro no tumba al resto de cuentas."""
        a = crear_carpeta(self.base, 'i', 'tok-i', 'i@x.es')
        raro = os.path.join(self.base, 'raro')
        os.makedirs(raro)
        with open(os.path.join(raro, '.credentials.json'), 'w', encoding='utf-8') as f:
            json.dump({'claudeAiOauth': {'accessToken': 't', 'expiresAt': 'mañana'}}, f)
        ok = lambda url, token=None, cuerpo=None: USO_REAL  # noqa: E731
        orig = uso.RUTA_CACHE
        uso.RUTA_CACHE = os.path.join(self.base, 'cache.json')
        try:
            r = uso.consultar_todas([{'alias': 'Raro', 'dir': raro}, {'alias': 'I', 'dir': a}], ok)
        finally:
            uso.RUTA_CACHE = orig
        self.assertEqual(r[0]['estado'], 'error')
        self.assertEqual(r[1]['sesion']['pct'], 10)
        self.assertEqual((r[0]['nombre'], r[1]['nombre']), ('Raro', 'I'))  # alias mientras no hay email; 'i@x.es' -> 'I'

    def test_cuentas_json(self):
        ruta = os.path.join(self.base, 'cuentas.json')
        self.assertEqual(uso.cargar_cuentas(ruta)[0]['dir'], '~/.claude')  # sin fichero
        with open(ruta, 'w', encoding='utf-8') as f:
            f.write('{"cuentas": [ {"alias": "A",} ]}')
        with self.assertRaises(ValueError):
            uso.cargar_cuentas(ruta)


    def _contador(self, uso_resp):
        n = {'uso': 0}

        def http(url, token=None, cuerpo=None):
            if url == uso.URL_USO:
                n['uso'] += 1
                return uso_resp
            return {'account': {'email': 'j@x.es'}, 'organization': {'name': 'Org'}}
        return n, http

    def test_reposo_si_no_cambia(self):
        """Sin cambios durante 5 min se consulta cada 5 min; con actividad, cada minuto."""
        from datetime import datetime, timezone
        d = crear_carpeta(self.base, 'j', 'tok-j', 'j@x.es')
        t0 = time.time()
        futuro = datetime.fromtimestamp(t0 + 86400, tz=timezone.utc).isoformat()
        resp = {'five_hour': {'utilization': 10.0, 'resets_at': futuro},
                'seven_day': {'utilization': 12.0, 'resets_at': futuro}}
        n, http = self._contador(resp)
        cache, cu = {}, {'alias': 'J', 'dir': d}
        uso.consultar_cuenta(cu, cache, http, ahora=t0)
        uso.consultar_cuenta(cu, cache, http, ahora=t0 + 30)
        self.assertEqual(n['uso'], 1)                        # dentro de los 60 s
        uso.consultar_cuenta(cu, cache, http, ahora=t0 + 70)
        self.assertEqual(n['uso'], 2)                        # al minuto, vuelve a mirar
        uso.consultar_cuenta(cu, cache, http, ahora=t0 + 310)
        self.assertEqual(n['uso'], 2)                        # 5 min sin cambios: reposo, no consulta
        r = uso.consultar_cuenta(cu, cache, http, ahora=t0 + 380)
        self.assertEqual(n['uso'], 3)                        # pasan 5 min desde la última
        self.assertIsNone(r['dato_de'])                      # y el dato no se marca como antiguo
        resp['five_hour']['utilization'] = 15.0              # hay actividad: vuelve a cada minuto
        uso.consultar_cuenta(cu, cache, http, ahora=t0 + 700)
        uso.consultar_cuenta(cu, cache, http, ahora=t0 + 770)
        self.assertEqual(n['uso'], 5)

    def test_reset_y_forzar_saltan_el_reposo(self):
        from datetime import datetime, timezone
        d = crear_carpeta(self.base, 'k', 'tok-k', 'k@x.es')
        t0 = time.time()
        reset = datetime.fromtimestamp(t0 + 100, tz=timezone.utc).isoformat()
        resp = {'five_hour': {'utilization': 10.0, 'resets_at': reset},
                'seven_day': {'utilization': 12.0, 'resets_at': reset}}
        n, http = self._contador(resp)
        cache, cu = {}, {'alias': 'K', 'dir': d}
        uso.consultar_cuenta(cu, cache, http, ahora=t0)
        cache[d]['uso_cambio_ts'] = t0 - 1000                # en reposo
        uso.consultar_cuenta(cu, cache, http, ahora=t0 + 90)
        self.assertEqual(n['uso'], 1)                        # reposo: no consulta
        uso.consultar_cuenta(cu, cache, http, ahora=t0 + 120)
        self.assertEqual(n['uso'], 2)                        # se reinició la ventana: consulta
        cache[d]['uso_cambio_ts'] = t0 - 1000
        uso.consultar_cuenta(cu, cache, http, ahora=t0 + 130, forzar=True)
        self.assertEqual(n['uso'], 3)                        # ⟳ siempre consulta


if __name__ == '__main__':
    unittest.main()
