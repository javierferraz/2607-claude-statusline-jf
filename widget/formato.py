"""Textos del widget: cuentas atrás, horas de reset y etiqueta del plan.

Equivalente en Python de src/format.ts, con el formato del panel de cuenta de Claude Code
(«resets in 2 h 14 min, at 13:20» / «resets in 5 d 4 h, Sat 16:00»).
"""
from datetime import datetime, timezone

DIAS_CORTOS = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom']


def a_fecha(resets_at):
    """ISO 8601 o epoch (s o ms) -> datetime local; None si no se entiende."""
    if resets_at in (None, ''):
        return None
    try:
        n = float(resets_at)
        return datetime.fromtimestamp(n / 1000 if n >= 1e10 else n)
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    try:
        d = datetime.fromisoformat(str(resets_at).replace('Z', '+00:00'))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    try:
        return d.astimezone().replace(tzinfo=None)
    except (OverflowError, OSError):
        return None


def cuenta_atras(resets_at, ahora=None):
    """'2 h 14 min', '45 min', '5 d 4 h'; '' si ya pasó o no hay fecha."""
    d = a_fecha(resets_at)
    if not d:
        return ''
    ahora = ahora or datetime.now()
    mins = int((d.timestamp() - ahora.timestamp()) // 60)  # timestamp() respeta el cambio de hora
    if mins <= 0:
        return ''
    dias, resto = divmod(mins, 1440)
    horas, m = divmod(resto, 60)
    if dias:
        return f'{dias} d {horas} h' if horas else f'{dias} d'
    if horas:
        return f'{horas} h {m} min' if m else f'{horas} h'
    return f'{m} min'


def texto_reset_sesion(resets_at, ahora=None):
    """'reset en 2 h 14 min, a las 13:20'."""
    d = a_fecha(resets_at)
    if not d:
        return ''
    c = cuenta_atras(resets_at, ahora)
    return f'reset en {c}, a las {d:%H:%M}' if c else f'reset a las {d:%H:%M}'


def texto_reset_semana(resets_at, ahora=None):
    """'reset en 5 d 4 h, sáb 16:00'."""
    d = a_fecha(resets_at)
    if not d:
        return ''
    cuando = f'{DIAS_CORTOS[d.weekday()]} {d:%H:%M}'
    c = cuenta_atras(resets_at, ahora)
    return f'reset en {c}, {cuando}' if c else f'reset {cuando}'


def etiqueta_plan(subscription_type, rate_limit_tier=None):
    """'team' + 'default_claude_max_5x' -> 'Team · Max 5x'."""
    if not subscription_type:
        return ''
    nombres = {'pro': 'Pro', 'team': 'Team', 'enterprise': 'Ent', 'free': 'Free', 'max': 'Max'}
    plan = nombres.get(subscription_type, subscription_type[:1].upper() + subscription_type[1:])
    tier = (rate_limit_tier or '').lower()
    for x in ('20x', '5x'):
        if f'max_{x}' in tier and plan != 'Max':
            return f'{plan} · Max {x}'
        if f'max_{x}' in tier:
            return f'Max {x}'
    return plan


def nombres_amistosos(emails):
    """Emails (None si no se conoce) -> nombres para mostrar (None si no hay email).

    Parte anterior a la @ en PROPER («ventas» -> «Ventas»). Si dos cuentas comparten esa parte,
    se le añade el dominio sin la terminación («Ventas Funidelia»); si aun así chocan, el email.
    """
    def partes(e):
        local, _, dominio = e.partition('@')
        return local, dominio.rsplit('.', 1)[0]

    ids = [partes(e)[0].lower() if e else None for e in emails]
    nombres = []
    for e, i in zip(emails, ids):
        if not e:
            nombres.append(None)
        elif ids.count(i) > 1:
            nombres.append(' '.join(x for x in partes(e) if x).title())
        else:
            nombres.append(partes(e)[0].title())
    return [e if n is not None and nombres.count(n) > 1 else n for e, n in zip(emails, nombres)]


def texto_mensual(mensual):
    """Créditos extra del mes (único dato mensual que da la API)."""
    if not mensual:
        return 'no disponible'
    if not mensual.get('activo'):
        return 'no disponible (créditos extra desactivados)'
    usado, limite, moneda = mensual.get('usado'), mensual.get('limite'), mensual.get('moneda') or ''
    if usado is None:
        return 'no disponible'
    if limite:
        return f'{usado:.2f} / {limite:.2f} {moneda}'.strip()
    return f'{usado:.2f} {moneda}'.strip()
