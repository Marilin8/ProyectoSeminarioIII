"""Cálculo de la planilla (nómina): salario base + comisiones del período.

Las comisiones no se guardan: se calculan al vuelo a partir de las citas
procesadas, igual que los reportes diarios. Por cada cita procesada del
período cobran comisión:

- el técnico que subió las imágenes del estudio, y
- el radiólogo asignado a la cita,

cada uno con su propio porcentaje según el convenio de la cita, aplicado
sobre el precio del estudio (que ya depende de convenio y horario
hábil/inhábil).
"""

import calendar
import datetime
from decimal import Decimal

from pacientes.models import Cita

CENTAVO = Decimal('0.01')

# convenio de la cita -> campo de % de comisión en Usuario
CONVENIO_A_CAMPO_PORCENTAJE = {
    Cita.CONVENIO_COEX: 'porcentaje_coex',
    Cita.CONVENIO_PRIVADO: 'porcentaje_privado',
    Cita.CONVENIO_EMERGENCIA_IGSS: 'porcentaje_emergencia_igss',
}

ROL_EN_CITA_TECNICO = 'Técnico'
ROL_EN_CITA_RADIOLOGO = 'Radiólogo'


def rango_mes(anio, mes):
    """(primer día, primer día del mes siguiente) para el mes dado."""
    inicio = datetime.date(anio, mes, 1)
    ultimo = calendar.monthrange(anio, mes)[1]
    fin = datetime.date(anio, mes, ultimo) + datetime.timedelta(days=1)
    return inicio, fin


def lineas_comision(desde, hasta):
    """Una línea por cada comisión ganada entre `desde` y `hasta` (fin
    exclusivo). Cada línea dice quién la ganó, en qué cita, cuándo, a qué
    paciente, con qué % y cuánto."""
    citas = (
        Cita.objects.filter(
            estado=Cita.ESTADO_PROCESADA, fecha__gte=desde, fecha__lt=hasta,
        )
        .select_related('paciente', 'tipo_estudio', 'radiologo')
        .prefetch_related(
            'tipo_estudio__precios',
            'orden_trabajo__imagenes__subida_por',
        )
        .order_by('fecha', 'hora')
    )

    lineas = []
    for cita in citas:
        precio = cita.precio
        habil = cita.horario_habil
        campo_pct = CONVENIO_A_CAMPO_PORCENTAJE.get(cita.convenio)
        if campo_pct is None:
            continue

        participantes = []
        tecnico = cita.tecnico_asignado
        if tecnico is not None:
            participantes.append((ROL_EN_CITA_TECNICO, tecnico))
        if cita.radiologo_id:
            participantes.append((ROL_EN_CITA_RADIOLOGO, cita.radiologo))

        for rol_en_cita, persona in participantes:
            pct = getattr(persona, campo_pct, Decimal('0')) or Decimal('0')
            if pct <= 0:
                continue
            comision = (precio * pct / Decimal('100')).quantize(CENTAVO)
            lineas.append({
                'persona': persona,
                'persona_id': persona.id,
                'rol_en_cita': rol_en_cita,
                'cita_id': cita.id,
                'fecha': cita.fecha,
                'hora': cita.hora,
                'paciente': cita.paciente,
                'estudio': cita.tipo_estudio,
                'modalidad': cita.tipo_estudio.get_modalidad_display(),
                'convenio': cita.get_convenio_display(),
                'convenio_codigo': cita.convenio,
                'habil': habil,
                'precio': precio,
                'pct': pct,
                'comision': comision,
            })
    return lineas


def _resumen_agrupado(lineas):
    """Agrupa las líneas por (rol, modalidad, convenio, horario, %) para el
    resumen tipo «Técnico — 5 Rayos X inhábil COEX al 5% = Q…»."""
    grupos = {}
    for linea in lineas:
        clave = (
            linea['rol_en_cita'], linea['modalidad'], linea['convenio'],
            linea['habil'], linea['pct'],
        )
        grupo = grupos.setdefault(clave, {
            'rol_en_cita': linea['rol_en_cita'],
            'modalidad': linea['modalidad'],
            'convenio': linea['convenio'],
            'habil': linea['habil'],
            'pct': linea['pct'],
            'cantidad': 0,
            'base': Decimal('0.00'),
            'comision': Decimal('0.00'),
            'momentos': [],
        })
        grupo['cantidad'] += 1
        grupo['base'] += linea['precio']
        grupo['comision'] += linea['comision']
        grupo['momentos'].append((linea['fecha'], linea['hora']))
    return sorted(
        grupos.values(),
        key=lambda g: (g['rol_en_cita'], g['modalidad'], g['convenio'], not g['habil']),
    )


def _lineas_ya_pagadas(lineas):
    """Set de (cita_id, rol_en_cita) que ya están cubiertas por algún
    PagoComision (para no volver a pagarlas)."""
    from accounts.models import PagoComisionLinea

    if not lineas:
        return set()
    cita_ids = {l['cita_id'] for l in lineas}
    return set(
        PagoComisionLinea.objects.filter(cita_id__in=cita_ids)
        .values_list('cita_id', 'rol_en_cita')
    )


def marcar_pagadas(lineas):
    """Agrega a cada línea la clave `pagada` (bool) según si ya se pagó."""
    pagadas = _lineas_ya_pagadas(lineas)
    for linea in lineas:
        linea['pagada'] = (linea['cita_id'], linea['rol_en_cita']) in pagadas
    return lineas


def planilla(desde, hasta, usuarios):
    """Fila de planilla por cada usuario: salario base mensual y comisiones
    del período que TODAVÍA no se han pagado (más un aviso si quedaron
    comisiones sin pagar de antes del período). `desde`/`hasta` incluidos."""
    lineas = marcar_pagadas(lineas_comision(desde, hasta + datetime.timedelta(days=1)))

    # Comisiones sin pagar anteriores al período (para avisar al admin).
    hace_mucho = desde - datetime.timedelta(days=3650)
    lineas_previas = marcar_pagadas(lineas_comision(hace_mucho, desde))

    por_persona = {}
    for linea in lineas:
        acc = por_persona.setdefault(linea['persona_id'], {
            'pendiente': Decimal('0.00'), 'cantidad': 0, 'previa': Decimal('0.00'),
        })
        if not linea['pagada']:
            acc['pendiente'] += linea['comision']
            acc['cantidad'] += 1
    for linea in lineas_previas:
        if not linea['pagada']:
            acc = por_persona.setdefault(linea['persona_id'], {
                'pendiente': Decimal('0.00'), 'cantidad': 0, 'previa': Decimal('0.00'),
            })
            acc['previa'] += linea['comision']

    filas = []
    for usuario in usuarios:
        acc = por_persona.get(usuario.id) or {}
        filas.append({
            'usuario': usuario,
            'salario_base': usuario.salario_base,
            'comisiones': acc.get('pendiente', Decimal('0.00')),
            'cantidad_comisiones': acc.get('cantidad', 0),
            'comisiones_previas': acc.get('previa', Decimal('0.00')),
        })
    return filas


def lineas_pendientes_de(usuario, desde, hasta):
    """Líneas de comisión de `usuario` en [desde, hasta] (incluidos) que aún
    no se pagaron, listas para registrar el pago."""
    lineas = [
        l for l in lineas_comision(desde, hasta + datetime.timedelta(days=1))
        if l['persona_id'] == usuario.id
    ]
    marcar_pagadas(lineas)
    return [l for l in lineas if not l['pagada']]


def detalle_empleado(desde, hasta, usuario):
    """Comisiones de `usuario` en el período: resumen agrupado y detalle
    línea por línea, marcando cuáles ya se pagaron."""
    lineas = [
        l for l in lineas_comision(desde, hasta + datetime.timedelta(days=1))
        if l['persona_id'] == usuario.id
    ]
    marcar_pagadas(lineas)
    pendientes = [l for l in lineas if not l['pagada']]
    total_pendiente = sum((l['comision'] for l in pendientes), Decimal('0.00'))
    total_pagado = sum((l['comision'] for l in lineas if l['pagada']), Decimal('0.00'))
    return {
        'lineas': lineas,
        'resumen': _resumen_agrupado(pendientes),
        'total_pendiente': total_pendiente,
        'total_pagado': total_pagado,
    }
