"""Resolución del período de la planilla a partir del querystring.

Modos:
- ``mes``      -> ?mes=YYYY-MM                 (mes completo)
- ``semana``   -> ?semana=YYYY-MM-DD           (lunes a domingo de esa semana)
- ``quincena`` -> ?quincena=YYYY-MM&q=1|2      (1–15 o 16–fin de mes)
- ``rango``    -> ?desde=YYYY-MM-DD&hasta=YYYY-MM-DD

Sin parámetros: el mes actual.

`resolver_periodo` devuelve un dict con:
- ``modo``: el modo resuelto
- ``desde`` / ``hasta``: date, ambos incluidos
- ``etiqueta``: texto para mostrar
- ``mes_valor``, ``semana_valor``, ``quincena_mes``, ``quincena_q``: para
  rellenar los inputs del formulario
"""

import calendar
import datetime

from django.utils import timezone
from django.utils.dateparse import parse_date

MESES = [
    '', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
    'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]


def _rango_mes(anio, mes):
    ultimo = calendar.monthrange(anio, mes)[1]
    return datetime.date(anio, mes, 1), datetime.date(anio, mes, ultimo)


def _base(modo, desde, hasta, etiqueta, hoy):
    return {
        'modo': modo,
        'desde': desde,
        'hasta': hasta,
        'etiqueta': etiqueta,
        'mes_valor': (desde if modo == 'mes' else hoy).strftime('%Y-%m'),
        'semana_valor': (desde if modo == 'semana' else hoy).strftime('%Y-%m-%d'),
        'quincena_mes': (desde if modo == 'quincena' else hoy).strftime('%Y-%m'),
        'quincena_q': '2' if (modo == 'quincena' and desde.day > 15) else '1',
        'desde_valor': desde.strftime('%Y-%m-%d') if modo == 'rango' else '',
        'hasta_valor': hasta.strftime('%Y-%m-%d') if modo == 'rango' else '',
    }


def resolver_periodo(request):
    hoy = timezone.localdate()
    modo = request.GET.get('modo') or ''

    if modo == 'semana':
        ref = parse_date(request.GET.get('semana', '')) or hoy
        lunes = ref - datetime.timedelta(days=ref.weekday())
        domingo = lunes + datetime.timedelta(days=6)
        etiqueta = f'Semana del {lunes:%d/%m/%Y} al {domingo:%d/%m/%Y}'
        return _base('semana', lunes, domingo, etiqueta, hoy)

    if modo == 'quincena':
        mes_txt = request.GET.get('quincena') or hoy.strftime('%Y-%m')
        try:
            anio, mes = (int(p) for p in mes_txt.split('-')[:2])
            datetime.date(anio, mes, 1)
        except (ValueError, TypeError):
            anio, mes = hoy.year, hoy.month
        segunda = request.GET.get('q') == '2'
        if segunda:
            desde = datetime.date(anio, mes, 16)
            hasta = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1])
        else:
            desde = datetime.date(anio, mes, 1)
            hasta = datetime.date(anio, mes, 15)
        etiqueta = f'{"2ª" if segunda else "1ª"} quincena de {MESES[mes]} {anio}'
        return _base('quincena', desde, hasta, etiqueta, hoy)

    if modo == 'rango':
        desde = parse_date(request.GET.get('desde', ''))
        hasta = parse_date(request.GET.get('hasta', ''))
        if not (desde and hasta and desde <= hasta):
            # Todavía no eligió fechas: se muestra el modo rango con el mes
            # actual como valores iniciales para que aparezcan los campos.
            desde, hasta = _rango_mes(hoy.year, hoy.month)
        etiqueta = f'{desde:%d/%m/%Y} al {hasta:%d/%m/%Y}'
        return _base('rango', desde, hasta, etiqueta, hoy)

    # Por defecto: mes (el indicado o el actual).
    mes_txt = request.GET.get('mes') or ''
    anio, mes = hoy.year, hoy.month
    if mes_txt:
        try:
            anio, mes = (int(p) for p in mes_txt.split('-')[:2])
            datetime.date(anio, mes, 1)
        except (ValueError, TypeError):
            anio, mes = hoy.year, hoy.month
    desde, hasta = _rango_mes(anio, mes)
    return _base('mes', desde, hasta, f'{MESES[mes]} {anio}', hoy)


def querystring(periodo):
    """Reconstruye el querystring del período para pasarlo en enlaces."""
    from django.utils.http import urlencode

    modo = periodo['modo']
    if modo == 'semana':
        return urlencode({'modo': 'semana', 'semana': periodo['semana_valor']})
    if modo == 'quincena':
        return urlencode({
            'modo': 'quincena', 'quincena': periodo['quincena_mes'], 'q': periodo['quincena_q'],
        })
    if modo == 'rango':
        return urlencode({
            'modo': 'rango', 'desde': periodo['desde_valor'], 'hasta': periodo['hasta_valor'],
        })
    return urlencode({'modo': 'mes', 'mes': periodo['mes_valor']})
