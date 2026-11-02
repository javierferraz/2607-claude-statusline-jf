"""Datos de uso de varias cuentas de Claude, una carpeta de configuración por cuenta.

Mismo origen que la extensión (src/dataSource.ts): el token OAuth de Claude Code en
<carpeta>/.credentials.json y el servicio de uso de Anthropic. Cada cuenta se resuelve
por separado: un fallo en una no afecta a las demás ni se mezcla con sus datos.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from formato import a_fecha, etiqueta_plan, nombres_amistosos

URL_USO = 'https://api.anthropic.com/api/oauth/usage'
URL_PERFIL = 'https://api.anthropic.com/api/oauth/profile'
CABECERAS = {'anthropic-beta': 'oauth-2025-04-20', 'Content-Type': 'application/json'}

CACHE_USO_S = 60
# Si los datos no cambian en SIN_CAMBIOS_S, se consulta solo cada CACHE_USO_REPOSO_S.
SIN_CAMBIOS_S = 300
CACHE_USO_REPOSO_S = 300
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


class LoginPerdido(Exception):
    """Claude Code dice que la cuenta ya no tiene sesión: hay que volver a iniciarla."""


def _claude_exe():
    candidatos = [os.path.join(os.environ.get('APPDATA', ''), 'npm', 'node_modules', '@anthropic-ai', 'claude-code', 'bin', 'claude.exe'),
                  shutil.which('claude.exe') or '']
    return next((c for c in candidatos if c and os.path.isfile(c)), None)


def _ejecutar_claude(carpeta):
    """Una llamada mínima del Claude Code oficial sobre la carpeta de la cuenta (haiku, sin herramientas, sin
    guardar sesión: unos 0,003 USD). Es él quien renueva y guarda el token; Cronos no habla con el servidor
    de renovación (no es público y rechaza a los clientes que no son Claude Code)."""
    exe = _claude_exe()
    if not exe:
        raise FileNotFoundError('claude.exe not found')
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('CLAUDE')}
    env['CLAUDE_CONFIG_DIR'] = carpeta
    with tempfile.TemporaryDirectory() as trabajo:
        r = subprocess.run([exe, '-p', 'Reply with exactly: ok', '--model', 'haiku', '--no-session-persistence',
                            '--tools', '', '--output-format', 'json'],
                           env=env, cwd=trabajo, capture_output=True, text=True, timeout=180,
                           creationflags=0x08000000 if os.name == 'nt' else 0)  # sin ventana de consola
    if r.returncode != 0:
        salida = (r.stdout + r.stderr).strip()
        if 'login' in salida.lower():
            raise LoginPerdido(salida[:120])
        raise RuntimeError(f'claude exited with {r.returncode}: {salida[:120]}')


def renovar_token(ruta_cred):
    """Renueva el token de una carpeta propia de Cronos con el Claude Code oficial. Devuelve el bloque
    claudeAiOauth nuevo; falla si el token no avanzó."""
    antes = float(_objeto(_objeto(_leer_json(ruta_cred)).get('claudeAiOauth')).get('expiresAt') or 0)
    _ejecutar_claude(os.path.dirname(ruta_cred))
    oauth = _objeto(_objeto(_leer_json(ruta_cred)).get('claudeAiOauth'))
    if not oauth.get('accessToken') or float(oauth.get('expiresAt') or 0) <= antes:
        raise ValueError('Claude Code did not renew the token')
    return oauth


def _es_este_pc(carpeta):
    """True si es la carpeta de configuración de Claude Code de este PC (~/.claude)."""
    return os.path.normcase(carpeta) == os.path.normcase(expandir('~/.claude'))


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


def _ttl_uso(c, ahora):
    """Cada cuánto se vuelve a pedir el uso: 60 s con actividad, 5 min si lleva 5 min sin cambiar."""
    sin_cambios = ahora - c.get('uso_cambio_ts', ahora)
    return CACHE_USO_REPOSO_S if sin_cambios >= SIN_CAMBIOS_S else CACHE_USO_S


def _reset_pasado(c, ahora):
    """True si una ventana se reinició después de la última consulta (el dato guardado ya no vale)."""
    uso = c.get('uso') or {}
    for k in ('five_hour', 'seven_day'):
        d = a_fecha((uso.get(k) or {}).get('resets_at'))
        if d and c.get('uso_ts', 0) < d.timestamp() <= ahora:
            return True
    return False


def _firma(uso):
    return [(uso.get(k) or {}).get('utilization') for k in ('five_hour', 'seven_day')] +         [(uso.get('extra_usage') or {}).get('used_credits')]


def _ventana(bloque):
    if not isinstance(bloque, dict) or bloque.get('utilization') is None:
        return None
    return {'pct': round(float(bloque['utilization'])), 'reset': bloque.get('resets_at')}


def consultar_cuenta(cuenta, cache, http=_http, ahora=None, forzar=False):
    """Devuelve el estado de una cuenta; los fallos esperables van en 'estado'/'error'."""
    ahora = ahora or time.time()
    alias = cuenta.get('alias') or cuenta.get('dir')
    carpeta = expandir(cuenta.get('dir') or '~/.claude')
    ruta_cred = os.path.join(carpeta, '.credentials.json')
    c = cache.setdefault(carpeta, {})
    res = {'alias': alias, 'nombre': alias, 'dir': carpeta, 'esta': _es_este_pc(carpeta), 'email': None, 'org': None, 'plan': '',
           'sesion': None, 'semana': None, 'mensual': None,
           'estado': 'ok', 'error': None, 'dato_de': None}

    email, org = _identidad_local(carpeta)
    res['email'], res['org'] = email, org

    oauth = _objeto(_objeto(_leer_json(ruta_cred)).get('claudeAiOauth'))
    if not oauth.get('accessToken'):
        res['estado'], res['error'] = 'sin_credenciales', 'not signed in on this folder'
        return res
    res['plan'] = etiqueta_plan(oauth.get('subscriptionType'), oauth.get('rateLimitTier'))

    caduca = float(oauth.get('expiresAt') or 0) / 1000
    renovado = False
    if caduca and caduca - ahora < MARGEN_CADUCIDAD_S:
        if cuenta.get('renovar') and ahora >= c.get('renovar_espera_hasta', 0):
            try:
                oauth = renovar_token(ruta_cred)
                renovado = True
                nuevo = float(oauth.get('expiresAt') or 0) / 1000
                c['renovar_espera_hasta'] = 0 if nuevo - ahora >= MARGEN_CADUCIDAD_S else ahora + ESPERA_RENOVAR_S
            except Exception as e:  # noqa: BLE001
                c['renovar_espera_hasta'] = ahora + ESPERA_RENOVAR_S
                if isinstance(e, LoginPerdido):
                    res['estado'], res['error'] = 'token_caducado', 'the login was lost; sign in again'
                elif caduca <= ahora:
                    res['estado'], res['error'] = 'token_caducado', f'could not renew the token ({e}); will retry'
        if res['estado'] == 'ok' and not renovado and caduca <= ahora:
            res['estado'] = 'token_caducado'
            res['error'] = ('token expired; renewal will be retried' if cuenta.get('renovar')
                            else 'token expired; it renews when Claude Code uses this account')

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
        fresco = (c.get('uso') is not None and not forzar and not _reset_pasado(c, ahora)
                  and ahora - c.get('uso_ts', 0) < _ttl_uso(c, ahora))
        bloqueado = ahora < c.get('espera_hasta', 0)
        if not fresco and not bloqueado:
            try:
                uso = http(URL_USO, token)
                if uso.get('five_hour') or uso.get('seven_day'):
                    if _firma(uso) != c.get('uso_firma'):
                        c['uso_firma'], c['uso_cambio_ts'] = _firma(uso), ahora
                    c['uso'], c['uso_ts'], c['espera_hasta'] = uso, ahora, 0
                else:
                    res['error'] = 'the API returned no usage data'
            except ErrorHttp as e:
                if e.status == 429:
                    try:
                        espera = float(e.retry_after)
                    except (TypeError, ValueError):
                        espera = 0
                    c['espera_hasta'] = ahora + (espera if espera > 0 else ESPERA_429_S)
                    res['error'] = 'rate limited by the API (429); retrying later'
                elif e.status == 401:
                    res['estado'], res['error'] = 'token_caducado', 'token rejected (401); sign in again'
                else:
                    res['error'] = f'API error ({e.status})'
            except Exception as e:  # noqa: BLE001 - red caída, timeout...
                res['error'] = f'no connection to the API ({type(e).__name__})'

    uso = c.get('uso')
    if uso and res['estado'] == 'ok':
        res['sesion'] = _ventana(uso.get('five_hour'))
        res['semana'] = _ventana(uso.get('seven_day'))
        res['mensual'] = _mensual(uso.get('extra_usage'))
        if ahora - c.get('uso_ts', ahora) >= _ttl_uso(c, ahora) * 2:
            res['dato_de'] = c.get('uso_ts')
    elif res['estado'] == 'ok' and not res['error']:
        res['error'] = 'no data yet'
    return res


def cargar_cuentas(ruta):
    """Lista de cuentas de cuentas.json. Sin fichero, solo ~/.claude; mal escrito, ValueError."""
    if not os.path.exists(ruta):
        return [{'alias': 'Cuenta 1', 'dir': '~/.claude', 'renovar': False}]
    datos = _leer_json(ruta)
    if isinstance(datos, dict):
        datos = datos.get('cuentas')
    if not isinstance(datos, list) or not datos or not all(isinstance(c, dict) for c in datos):
        raise ValueError(f'{os.path.basename(ruta)} is malformed: check the JSON')
    return datos


def _sin_duplicados(res):
    """La misma cuenta en dos carpetas (p. ej. ~/.claude y una propia) sale una sola vez, en el sitio de la
    primera: la fila que tiene datos, con la marca de «este PC» si alguna de las dos la tiene."""
    def con_datos(r):
        return r['estado'] == 'ok' and bool(r['sesion'] or r['semana'])
    salida, vistos = [], {}
    for r in res:
        clave = (r['email'] or '').lower()
        if not clave:
            salida.append(r)
        elif clave not in vistos:
            vistos[clave] = len(salida)
            salida.append(r)
        else:
            i = vistos[clave]
            previa = salida[i]
            esta = previa['esta'] or r['esta']
            if con_datos(r) and not con_datos(previa):
                salida[i] = previa = r
            previa['esta'] = esta
    return salida


def consultar_todas(cuentas, http=_http, forzar=False):
    cache = cargar_cache()
    res = []
    for c in cuentas:
        try:
            res.append(consultar_cuenta(c, cache, http, forzar=forzar))
        except Exception as e:  # noqa: BLE001 - un fallo inesperado solo afecta a su cuenta
            res.append({'alias': c.get('alias') or c.get('dir'), 'nombre': c.get('alias') or c.get('dir'),
                        'dir': c.get('dir'), 'esta': False, 'email': None, 'org': None,
                        'plan': '', 'sesion': None, 'semana': None, 'mensual': None, 'estado': 'error',
                        'error': f'error reading the account ({type(e).__name__})', 'dato_de': None})
    guardar_cache(cache)
    res = _sin_duplicados(res)
    # Nombre para mostrar a partir del email; el alias de cuentas.json solo vale mientras no se conoce.
    for r, n in zip(res, nombres_amistosos([r['email'] for r in res])):
        r['nombre'] = n or r['alias']
    return res
