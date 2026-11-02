"""Datos de uso de varias cuentas de Claude, una carpeta de configuración por cuenta.

Mismo origen que la extensión (src/dataSource.ts): el token OAuth de Claude Code en
<carpeta>/.credentials.json y el servicio de uso de Anthropic. Cada cuenta se resuelve
por separado: un fallo en una no afecta a las demás ni se mezcla con sus datos.
"""
import json
import os
import tempfile
import time
import urllib.error
import urllib.request

from formato import etiqueta_plan

URL_USO = 'https://api.anthropic.com/api/oauth/usage'
URL_PERFIL = 'https://api.anthropic.com/api/oauth/profile'
# Sacados del binario de Claude Code (no documentados): los mismos que usa para renovar su token.
URL_TOKEN = 'https://platform.claude.com/v1/oauth/token'
CLIENT_ID = '9d1c250a-e61b-44d9-88ed-5944d1962f5e'
CABECERAS = {'anthropic-beta': 'oauth-2025-04-20', 'Content-Type': 'application/json'}

CACHE_USO_S = 60
CACHE_PERFIL_S = 3600
ESPERA_429_S = 300
ESPERA_RENOVAR_S = 300
MARGEN_CADUCIDAD_S = 300

CARPETA_ESTADO = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'ClaudeCuentasWidget')
RUTA_CACHE = os.path.join(CARPETA_ESTADO, 'cache.json')


class ErrorHttp(Exception):
    def __init__(self, status, retry_after=None):
        super().__init__(f'HTTP {status}')
        self.status = status
        self.retry_after = retry_after


def _http(url, token=None, cuerpo=None, timeout=10):
    cab = dict(CABECERAS)
    if token:
        cab['Authorization'] = f'Bearer {token}'
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, headers=cab, method='POST' if datos else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise ErrorHttp(e.code, e.headers.get('retry-after')) from None


def expandir(ruta):
    return os.path.normpath(os.path.expandvars(os.path.expanduser(ruta)))


def _leer_json(ruta):
    try:
        with open(ruta, encoding='utf-8') as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return None
    return datos


def _escribir_json_atomico(ruta, datos, intentos=1):
    carpeta = os.path.dirname(ruta)
    os.makedirs(carpeta, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=carpeta, prefix='.widget-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(datos, f)
        for i in range(intentos):
            try:
                os.replace(tmp, ruta)
                break
            except PermissionError:
                if i == intentos - 1:
                    raise
                time.sleep(0.5)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def cargar_cache():
    return _leer_json(RUTA_CACHE) or {}


def guardar_cache(cache):
    try:
        _escribir_json_atomico(RUTA_CACHE, cache)
    except OSError:
        pass


def _objeto(v):
    return v if isinstance(v, dict) else {}


def renovar_token(ruta_cred, http=_http):
    """Renueva el token de una carpeta propia del widget. Devuelve el bloque claudeAiOauth nuevo."""
    creds = _objeto(_leer_json(ruta_cred))  # se relee justo antes por si otro proceso lo cambió
    oauth = _objeto(creds.get('claudeAiOauth'))
    if not oauth.get('refreshToken'):
        raise ValueError('sin refreshToken')
    r = http(URL_TOKEN, cuerpo={
        'grant_type': 'refresh_token',
        'refresh_token': oauth['refreshToken'],
        'client_id': CLIENT_ID,
        'scope': ' '.join(oauth.get('scopes') or []),
    })
    if not r.get('access_token'):
        raise ValueError('respuesta sin access_token')
    oauth['accessToken'] = r['access_token']
    oauth['refreshToken'] = r.get('refresh_token') or oauth['refreshToken']
    if r.get('expires_in') is not None:
        oauth['expiresAt'] = int((time.time() + float(r['expires_in'])) * 1000)
    creds['claudeAiOauth'] = oauth
    # El servidor ya ha invalidado el refresh_token anterior: perder esta escritura obliga a
    # volver a iniciar sesión, así que se reintenta si el fichero está bloqueado.
    _escribir_json_atomico(ruta_cred, creds, intentos=10)
    return oauth


def _identidad_local(carpeta):
    """Email y organización de <carpeta>/.claude.json (o ~/.claude.json para la carpeta por defecto)."""
    candidatos = [os.path.join(carpeta, '.claude.json')]
    if os.path.normcase(carpeta) == os.path.normcase(expandir('~/.claude')):
        candidatos.append(expandir('~/.claude.json'))
    for ruta in candidatos:
        cuenta = _objeto(_objeto(_leer_json(ruta)).get('oauthAccount'))
        if cuenta.get('emailAddress'):
            return cuenta.get('emailAddress'), cuenta.get('organizationName') or ''
    return None, None


def _mensual(extra):
    if not isinstance(extra, dict):
        return None
    dec = extra.get('decimal_places')
    div = 10 ** dec if isinstance(dec, int) else 1

    def n(v):
        return None if v is None else float(v) / div
    return {'activo': bool(extra.get('is_enabled')), 'usado': n(extra.get('used_credits')),
            'limite': n(extra.get('monthly_limit')), 'moneda': extra.get('currency')}


def _ventana(bloque):
    if not isinstance(bloque, dict) or bloque.get('utilization') is None:
        return None
    return {'pct': round(float(bloque['utilization'])), 'reset': bloque.get('resets_at')}


def consultar_cuenta(cuenta, cache, http=_http, ahora=None):
    """Devuelve el estado de una cuenta; los fallos esperables van en 'estado'/'error'."""
    ahora = ahora or time.time()
    alias = cuenta.get('alias') or cuenta.get('dir')
    carpeta = expandir(cuenta.get('dir') or '~/.claude')
    ruta_cred = os.path.join(carpeta, '.credentials.json')
    c = cache.setdefault(carpeta, {})
    res = {'alias': alias, 'dir': carpeta, 'email': None, 'org': None, 'plan': '',
           'sesion': None, 'semana': None, 'mensual': None,
           'estado': 'ok', 'error': None, 'dato_de': None}

    email, org = _identidad_local(carpeta)
    res['email'], res['org'] = email, org

    oauth = _objeto(_objeto(_leer_json(ruta_cred)).get('claudeAiOauth'))
    if not oauth.get('accessToken'):
        res['estado'], res['error'] = 'sin_credenciales', 'sin sesión iniciada en esta carpeta'
        return res
    res['plan'] = etiqueta_plan(oauth.get('subscriptionType'), oauth.get('rateLimitTier'))

    caduca = float(oauth.get('expiresAt') or 0) / 1000
    renovado = False
    if caduca and caduca - ahora < MARGEN_CADUCIDAD_S:
        if cuenta.get('renovar') and ahora >= c.get('renovar_espera_hasta', 0):
            try:
                oauth = renovar_token(ruta_cred, http)
                renovado = True
                # Sin expires_in en la respuesta no se sabe cuándo caduca: no se reintenta en cada ciclo.
                nuevo = float(oauth.get('expiresAt') or 0) / 1000
                c['renovar_espera_hasta'] = 0 if nuevo - ahora >= MARGEN_CADUCIDAD_S else ahora + ESPERA_RENOVAR_S
            except Exception as e:  # noqa: BLE001
                c['renovar_espera_hasta'] = ahora + ESPERA_RENOVAR_S
                if isinstance(e, ErrorHttp) and e.status in (400, 401):
                    res['estado'], res['error'] = 'token_caducado', f'no se pudo renovar el token ({e}); vuelve a iniciar sesión'
                elif caduca <= ahora:
                    res['estado'], res['error'] = 'token_caducado', f'no se pudo renovar el token ({e}); se reintentará'
        if res['estado'] == 'ok' and not renovado and caduca <= ahora:
            res['estado'] = 'token_caducado'
            res['error'] = ('token caducado; se reintentará la renovación' if cuenta.get('renovar')
                            else 'token caducado; se renovará al usar Claude Code con esta cuenta')

    token = oauth.get('accessToken')
    if res['estado'] == 'ok':
        # Perfil (email y organización), cacheado una hora.
        perfil = c.get('perfil')
        if not perfil or ahora - c.get('perfil_ts', 0) > CACHE_PERFIL_S:
            try:
                p = http(URL_PERFIL, token)
                perfil = {'email': (p.get('account') or {}).get('email'),
                          'org': (p.get('organization') or {}).get('name')}
                c['perfil'], c['perfil_ts'] = perfil, ahora
            except Exception:  # noqa: BLE001 - se usa lo local
                pass
        if perfil and perfil.get('email'):
            res['email'], res['org'] = perfil['email'], perfil.get('org') or res['org']

        # Uso, cacheado y con espera tras un 429 (como fetchOAuthUsage en src/dataSource.ts).
        fresco = c.get('uso') is not None and ahora - c.get('uso_ts', 0) < CACHE_USO_S
        bloqueado = ahora < c.get('espera_hasta', 0)
        if not fresco and not bloqueado:
            try:
                uso = http(URL_USO, token)
                if uso.get('five_hour') or uso.get('seven_day'):
                    c['uso'], c['uso_ts'], c['espera_hasta'] = uso, ahora, 0
                else:
                    res['error'] = 'la API no devolvió datos de uso'
            except ErrorHttp as e:
                if e.status == 429:
                    try:
                        espera = float(e.retry_after)
                    except (TypeError, ValueError):
                        espera = 0
                    c['espera_hasta'] = ahora + (espera if espera > 0 else ESPERA_429_S)
                    res['error'] = 'límite de consultas de la API (429); reintento más tarde'
                elif e.status == 401:
                    res['estado'], res['error'] = 'token_caducado', 'token rechazado (401); vuelve a iniciar sesión'
                else:
                    res['error'] = f'error de la API ({e.status})'
            except Exception as e:  # noqa: BLE001 - red caída, timeout...
                res['error'] = f'sin conexión con la API ({type(e).__name__})'

    uso = c.get('uso')
    if uso and res['estado'] == 'ok':
        res['sesion'] = _ventana(uso.get('five_hour'))
        res['semana'] = _ventana(uso.get('seven_day'))
        res['mensual'] = _mensual(uso.get('extra_usage'))
        if ahora - c.get('uso_ts', ahora) >= CACHE_USO_S * 2:
            res['dato_de'] = c.get('uso_ts')
    elif res['estado'] == 'ok' and not res['error']:
        res['error'] = 'sin datos todavía'
    return res


def cargar_cuentas(ruta):
    """Lista de cuentas de cuentas.json. Sin fichero, solo ~/.claude; mal escrito, ValueError."""
    if not os.path.exists(ruta):
        return [{'alias': 'Cuenta 1', 'dir': '~/.claude', 'renovar': False}]
    datos = _leer_json(ruta)
    if isinstance(datos, dict):
        datos = datos.get('cuentas')
    if not isinstance(datos, list) or not datos or not all(isinstance(c, dict) for c in datos):
        raise ValueError(f'{os.path.basename(ruta)} mal escrito: revisa el JSON')
    return datos


def consultar_todas(cuentas, http=_http):
    cache = cargar_cache()
    res = []
    for c in cuentas:
        try:
            res.append(consultar_cuenta(c, cache, http))
        except Exception as e:  # noqa: BLE001 - un fallo inesperado solo afecta a su cuenta
            res.append({'alias': c.get('alias') or c.get('dir'), 'dir': c.get('dir'), 'email': None, 'org': None,
                        'plan': '', 'sesion': None, 'semana': None, 'mensual': None, 'estado': 'error',
                        'error': f'error leyendo la cuenta ({type(e).__name__})', 'dato_de': None})
    guardar_cache(cache)
    return res
