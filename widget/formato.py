"""Textos del widget: cuentas atrás, horas de reset y etiqueta del plan.

Equivalente en Python de src/format.ts, con el formato del panel de cuenta de Claude Code
(«resets in 2 h 14 min, at 13:20» / «resets in 5 d 4 h, Sat 16:00»).
"""
from datetime import datetime, timezone

DIAS_CORTOS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
SESION_MIN, SEMANA_MIN = 300, 10080


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
    """'resets in 2 h 14 min, at 13:20' (formato del panel de Claude Code y de Roaring Lion)."""
    d = a_fecha(resets_at)
    if not d:
        return ''
    c = cuenta_atras(resets_at, ahora)
    return f'resets in {c}, at {d:%H:%M}' if c else f'resets at {d:%H:%M}'


def texto_reset_semana(resets_at, ahora=None):
    """'resets in 5 d 4 h, Sat 16:00'."""
    d = a_fecha(resets_at)
    if not d:
        return ''
    cuando = f'{DIAS_CORTOS[d.weekday()]} {d:%H:%M}'
    c = cuenta_atras(resets_at, ahora)
    return f'resets in {c}, {cuando}' if c else f'resets {cuando}'


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


def dia_hora(d):
    """'Tue 15:41'."""
    return f'{DIAS_CORTOS[d.weekday()]} {d:%H:%M}'


def texto_extra(mensual):
    """Créditos extra del mes (único dato mensual que da la API), para la columna del plan."""
    if not mensual or not mensual.get('activo') or mensual.get('usado') is None:
        return 'Extra credits —'
    usado, limite, moneda = mensual['usado'], mensual.get('limite'), mensual.get('moneda') or ''
    if limite:
        return f'Extra credits {usado:.2f} / {limite:.2f} {moneda}'.strip()
    return f'Extra credits {usado:.2f} {moneda}'.strip()


def ritmo(resets_at, span_min, ahora=None):
    """«Ritmo uniforme»: parte de la ventana ya gastada, en %. Es la raya blanca de Roaring Lion
    (S-772): llegar al 100 % justo en el reset es gastar lo mismo cada hora (o cada día).
    None si no hay hora de reset."""
    d = a_fecha(resets_at)
    if not d:
        return None
    ahora = ahora or datetime.now()
    restan = (d.timestamp() - ahora.timestamp()) / 60
    return min(100.0, max(0.0, (1 - restan / span_min) * 100))


def tramo(pct, ritmo_pct):
    """Color de la barra por ritmo (Roaring Lion, S-792): hasta 5 puntos por delante de la raya = ok,
    hasta 15 = warn, más = danger; ventana llena = danger. Añadido para Cronos: 'low' (más de 25 puntos
    por debajo de la raya: sobra cuota). Sin hora de reset, los tramos fijos de Lion (50 % / 80 %)."""
    if pct >= 100:
        return 'danger'
    if ritmo_pct is None:
        return 'danger' if pct >= 80 else 'warn' if pct >= 50 else 'ok'
    delante = pct - ritmo_pct
    return 'danger' if delante > 15 else 'warn' if delante > 5 else 'low' if delante < -25 else 'ok'


def se_agota(pct, resets_at, span_min, ahora=None):
    """Como `runsOut` de Lion: solo la semana y tras un día entero; cuándo llegaría al 100 % al ritmo
    medio de lo que va, si es antes del reset (datetime); None en otro caso."""
    if span_min != SEMANA_MIN or pct <= 0 or pct >= 100:
        return None
    d = a_fecha(resets_at)
    if not d:
        return None
    ahora = ahora or datetime.now()
    restan = (d.timestamp() - ahora.timestamp()) / 60
    gastado = span_min - restan
    if gastado < 1440:
        return None
    hasta = (100 - pct) / pct * gastado
    return datetime.fromtimestamp(ahora.timestamp() + hasta * 60) if hasta < restan else None
