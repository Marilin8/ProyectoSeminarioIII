"""Panel financiero del administrador.

"Producción" = valor de los estudios realizados (citas en proceso o procesadas) en el
período, con el mismo precio que usan Caja y el reporte diario (Cita.precio: el estudio
agendado más los estudios extra marcados procesar_ahora, con la tarifa vigente en la
fecha de la cita). Las citas ausentes, rechazadas o todavía no atendidas no suman.

- Privado: lo cobra Caja (Cobro). Se separa en cobrado y pendiente de cobro.
- COEX y Emergencia IGSS: no se le cobran al paciente; es lo que se le factura al IGSS.

Para no hacer una consulta por cita, los precios se memorizan por
(estudio, convenio, horario, fecha): en un mes se repiten mucho.
"""
import csv
import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import Prefetch, Sum
from django.utils import timezone

from pacientes.models import (
    Cita, EstudioExtra, MedicoTratante, PagoComisionMedicoTratante, TipoEstudio, es_horario_habil,
)

from .models import Usuario

CERO = Decimal('0.00')
ESTADOS_REALIZADOS = (Cita.ESTADO_EN_PROCESO, Cita.ESTADO_PROCESADA)
CONVENIOS_IGSS = (Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS)
COLORES_CONVENIO = {
    Cita.CONVENIO_PRIVADO: 'var(--morado-500)',
    Cita.CONVENIO_COEX: 'var(--cian-500)',
    Cita.CONVENIO_EMERGENCIA_IGSS: 'var(--cian-800)',
}
PERIODOS = (
    ('hoy', 'Hoy'),
    ('semana', 'Esta semana'),
    ('mes', 'Este mes'),
    ('mes_anterior', 'Mes anterior'),
    ('30', 'Últimos 30 días'),
    ('anio', 'Este año'),
    ('rango', 'Personalizado'),
)
PERIODO_POR_DEFECTO = 'mes'
MAX_FILAS = 10
MAX_DIAS_RANGO = 366
DIAS_SEMANA = ('Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom')


def _fecha(texto):
    try:
        return datetime.date.fromisoformat(texto or '')
    except ValueError:
        return None


def rango_del_periodo(periodo, desde_texto='', hasta_texto='', hoy=None):
    """(periodo válido, desde, hasta) — ambos días incluidos."""
    hoy = hoy or timezone.localdate()
    claves = dict(PERIODOS)
    periodo = periodo if periodo in claves else PERIODO_POR_DEFECTO
    if periodo == 'hoy':
        return periodo, hoy, hoy
    if periodo == 'semana':
        return periodo, hoy - datetime.timedelta(days=hoy.weekday()), hoy
    if periodo == 'mes':
        return periodo, hoy.replace(day=1), hoy
    if periodo == 'mes_anterior':
        fin = hoy.replace(day=1) - datetime.timedelta(days=1)
        return periodo, fin.replace(day=1), fin
    if periodo == '30':
        return periodo, hoy - datetime.timedelta(days=29), hoy
    if periodo == 'anio':
        return periodo, hoy.replace(month=1, day=1), hoy
    desde, hasta = _fecha(desde_texto), _fecha(hasta_texto)
    if not desde or not hasta:
        return rango_del_periodo(PERIODO_POR_DEFECTO, hoy=hoy)
    if desde > hasta:
        desde, hasta = hasta, desde
    if (hasta - desde).days >= MAX_DIAS_RANGO:
        desde = hasta - datetime.timedelta(days=MAX_DIAS_RANGO - 1)
    return 'rango', desde, hasta


def _entero(texto):
    try:
        return int(texto)
    except (TypeError, ValueError):
        return None


def leer_filtros(datos, hoy=None):
    """Filtros del formulario (request.GET), ya validados."""
    periodo, desde, hasta = rango_del_periodo(
        datos.get('periodo'), datos.get('desde'), datos.get('hasta'), hoy=hoy,
    )
    convenio = datos.get('convenio', '')
    if convenio not in dict(Cita.CONVENIO_CHOICES):
        convenio = ''
    return {
        'periodo': periodo, 'desde': desde, 'hasta': hasta, 'convenio': convenio,
        'estudio': _entero(datos.get('estudio')),
        'radiologo': _entero(datos.get('radiologo')),
        'medico': _entero(datos.get('medico')),
    }


def citas_del_periodo(filtros):
    citas = (
        Cita.objects
        .filter(fecha__range=(filtros['desde'], filtros['hasta']), estado__in=ESTADOS_REALIZADOS)
        .select_related('paciente', 'tipo_estudio', 'radiologo', 'medico_tratante', 'cobro', 'sucursal')
        .prefetch_related('tipo_estudio__precios', Prefetch(
            'estudios_extra',
            queryset=EstudioExtra.objects.filter(procesar_ahora=True)
            .select_related('tipo_estudio').prefetch_related('tipo_estudio__precios'),
            to_attr='extras_cobrados',
        ))
        .order_by('fecha', 'hora', 'id')
    )
    if filtros['convenio']:
        citas = citas.filter(convenio=filtros['convenio'])
    if filtros['estudio']:
        citas = citas.filter(tipo_estudio_id=filtros['estudio'])
    if filtros['radiologo']:
        citas = citas.filter(radiologo_id=filtros['radiologo'])
    if filtros['medico']:
        citas = citas.filter(medico_tratante_id=filtros['medico'])
    return citas


class _Precios:
    """Cita.precio con memoria por (estudio, convenio, horario hábil, fecha, sucursal)."""

    def __init__(self):
        self._memoria = {}

    def _de(self, estudio, convenio, habil, fecha, sucursal):
        clave = (estudio.id, convenio, habil, fecha, sucursal.id if sucursal else None)
        if clave not in self._memoria:
            self._memoria[clave] = estudio.precio_para(convenio, habil, fecha=fecha, sucursal=sucursal) or CERO
        return self._memoria[clave]

    def de_cita(self, cita):
        habil = es_horario_habil(cita.convenio, cita.hora)
        total = self._de(cita.tipo_estudio, cita.convenio, habil, cita.fecha, cita.sucursal)
        for extra in cita.extras_cobrados:
            total += self._de(extra.tipo_estudio, cita.convenio, habil, cita.fecha, cita.sucursal)
        return total


def _porcentaje(parte, total):
    return round(100 * parte / total) if total else 0


def _ranking(acumulado, total_general, nombres):
    """[{nombre, cantidad, monto, ancho, porcentaje}] de mayor a menor monto."""
    filas = sorted(acumulado.items(), key=lambda kv: (-kv[1]['monto'], -kv[1]['cantidad']))
    tope = filas[0][1]['monto'] if filas else CERO
    resultado = []
    for clave, datos in filas[:MAX_FILAS]:
        resultado.append({
            'id': clave,
            'nombre': nombres(clave),
            'cantidad': datos['cantidad'],
            'monto': datos['monto'],
            'ancho': max(round(float(100 * datos['monto'] / tope), 1), 1) if tope else 0,
            'porcentaje': _porcentaje(datos['monto'], total_general),
        })
    otros = filas[MAX_FILAS:]
    if otros:
        resultado.append({
            'id': None, 'nombre': f'Otros ({len(otros)})', 'otros': True,
            'cantidad': sum(d['cantidad'] for _c, d in otros),
            'monto': sum((d['monto'] for _c, d in otros), CERO),
            'ancho': 0, 'porcentaje': _porcentaje(sum((d['monto'] for _c, d in otros), CERO), total_general),
        })
        resultado[-1]['ancho'] = max(round(float(100 * resultado[-1]['monto'] / tope), 1), 1) if tope else 0
    return resultado


def _serie_por_dia(por_dia, desde, hasta):
    """Columnas de producción por día (si el rango es largo, por semana o por mes)."""
    dias = (hasta - desde).days + 1
    if dias <= 35:
        grupos = [(desde + datetime.timedelta(days=i),) * 2 for i in range(dias)]
        etiqueta = lambda ini, _fin: f'{DIAS_SEMANA[ini.weekday()]} {ini:%d/%m}' if dias <= 7 else f'{ini:%d/%m}'
    elif dias <= 120:
        grupos, inicio = [], desde
        while inicio <= hasta:
            fin = min(inicio + datetime.timedelta(days=6 - inicio.weekday()), hasta)
            grupos.append((inicio, fin))
            inicio = fin + datetime.timedelta(days=1)
        etiqueta = lambda ini, _fin: f'Sem {ini:%d/%m}'
    else:
        grupos, inicio = [], desde
        while inicio <= hasta:
            siguiente = (inicio.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
            fin = min(siguiente - datetime.timedelta(days=1), hasta)
            grupos.append((inicio, fin))
            inicio = fin + datetime.timedelta(days=1)
        etiqueta = lambda ini, _fin: f'{ini:%m/%Y}'

    columnas = []
    for inicio, fin in grupos:
        montos = defaultdict(lambda: CERO)
        for fecha, por_convenio in por_dia.items():
            if inicio <= fecha <= fin:
                for convenio, monto in por_convenio.items():
                    montos[convenio] += monto
        columnas.append({'etiqueta': etiqueta(inicio, fin), 'total': sum(montos.values(), CERO), 'montos': montos})
    tope = max((c['total'] for c in columnas), default=CERO) or Decimal('1')
    for c in columnas:
        c['alto'] = round(float(100 * c['total'] / tope), 1)
        c['segmentos'] = [
            {'nombre': nombre, 'color': COLORES_CONVENIO[clave], 'monto': c['montos'].get(clave, CERO),
             'alto': round(float(100 * c['montos'].get(clave, CERO) / c['total']), 1) if c['total'] else 0}
            for clave, nombre in Cita.CONVENIO_CHOICES if c['montos'].get(clave)
        ]
    return {'columnas': columnas, 'agrupado': 'día' if dias <= 35 else ('semana' if dias <= 120 else 'mes')}


def calcular(filtros):
    precios = _Precios()
    citas = list(citas_del_periodo(filtros))

    total = CERO
    por_convenio = defaultdict(lambda: {'cantidad': 0, 'monto': CERO})
    por_estudio = defaultdict(lambda: {'cantidad': 0, 'monto': CERO})
    por_radiologo = defaultdict(lambda: {'cantidad': 0, 'monto': CERO})
    por_medico = defaultdict(lambda: {'cantidad': 0, 'monto': CERO})
    por_forma = defaultdict(lambda: {'cantidad': 0, 'monto': CERO})
    por_horario = defaultdict(lambda: {'cantidad': 0, 'monto': CERO})
    por_dia = defaultdict(lambda: defaultdict(lambda: CERO))
    privado_cobrado = privado_pendiente = igss = CERO
    nombres_estudio, nombres_radiologo, nombres_medico = {}, {}, {}

    for cita in citas:
        precio = precios.de_cita(cita)
        cita.precio_calculado = precio
        total += precio
        for grupo, clave in ((por_convenio, cita.convenio), (por_estudio, cita.tipo_estudio_id),
                             (por_radiologo, cita.radiologo_id), (por_medico, cita.medico_tratante_id)):
            grupo[clave]['cantidad'] += 1
            grupo[clave]['monto'] += precio
        nombres_estudio[cita.tipo_estudio_id] = cita.tipo_estudio.nombre
        if cita.radiologo_id:
            nombres_radiologo[cita.radiologo_id] = cita.radiologo.get_full_name() or cita.radiologo.username
        if cita.medico_tratante_id:
            nombres_medico[cita.medico_tratante_id] = cita.medico_tratante.nombre
        habil = 'Hábil' if es_horario_habil(cita.convenio, cita.hora) else 'Inhábil (después de las 18:00)'
        por_horario[habil]['cantidad'] += 1
        por_horario[habil]['monto'] += precio
        por_dia[cita.fecha][cita.convenio] += precio

        if cita.convenio == Cita.CONVENIO_PRIVADO:
            cobro = getattr(cita, 'cobro', None)
            if cobro is not None and cobro.pagado:
                privado_cobrado += precio
                forma = cobro.get_forma_pago_display() or 'Sin indicar'
                por_forma[forma]['cantidad'] += 1
                por_forma[forma]['monto'] += precio
            else:
                privado_pendiente += precio
        else:
            igss += precio

    por_medico.pop(None, None)
    sin_radiologo = por_radiologo.pop(None, None)
    convenios = []
    for clave, nombre in Cita.CONVENIO_CHOICES:
        datos = por_convenio.get(clave, {'cantidad': 0, 'monto': CERO})
        convenios.append({'clave': clave, 'nombre': nombre, 'color': COLORES_CONVENIO[clave],
                          'cantidad': datos['cantidad'], 'monto': datos['monto'],
                          'porcentaje': _porcentaje(datos['monto'], total)})
    gradiente, acumulado = [], 0.0
    for c in convenios:
        if c['monto']:
            fin = acumulado + float(100 * c['monto'] / total)
            gradiente.append(f"{c['color']} {acumulado:.2f}% {fin:.2f}%")
            acumulado = fin

    referido = sum((d['monto'] for d in por_medico.values()), CERO)
    inicio = timezone.make_aware(datetime.datetime.combine(filtros['desde'], datetime.time.min))
    fin = timezone.make_aware(datetime.datetime.combine(filtros['hasta'] + datetime.timedelta(days=1), datetime.time.min))
    pagos = PagoComisionMedicoTratante.objects.filter(creado_en__gte=inicio, creado_en__lt=fin)
    if filtros['medico']:
        pagos = pagos.filter(medico_tratante_id=filtros['medico'])
    comisiones_pagadas = pagos.aggregate(total=Sum('monto'))['total'] or CERO

    return {
        'citas': citas,
        'kpi': {
            'produccion': total,
            'estudios': len(citas),
            'promedio': (total / len(citas)).quantize(Decimal('0.01')) if citas else CERO,
            'privado_cobrado': privado_cobrado,
            'privado_pendiente': privado_pendiente,
            'igss': igss,
            'referido': referido,
            'comisiones_pagadas': comisiones_pagadas,
            'dias': (filtros['hasta'] - filtros['desde']).days + 1,
        },
        'promedio_diario': (total / ((filtros['hasta'] - filtros['desde']).days + 1)).quantize(Decimal('0.01')),
        'convenios': convenios,
        'gradiente': ', '.join(gradiente) or 'var(--neutral-200) 0 100%',
        'serie': _serie_por_dia(por_dia, filtros['desde'], filtros['hasta']),
        'estudios': _ranking(por_estudio, total, lambda k: nombres_estudio.get(k, '—')),
        'radiologos': _ranking(por_radiologo, total, lambda k: nombres_radiologo.get(k, '—')),
        'sin_radiologo': sin_radiologo,
        'medicos': _ranking(por_medico, referido, lambda k: nombres_medico.get(k, '—')),
        'formas_pago': _ranking(por_forma, privado_cobrado, lambda k: k),
        'horarios': _ranking(por_horario, total, lambda k: k),
    }


def opciones_de_filtro():
    # Con sufijo _opciones: 'estudios', 'radiologos'... ya son los rankings de calcular().
    return {
        'periodos': PERIODOS,
        'estudios_opciones': TipoEstudio.objects.order_by('nombre').values_list('id', 'nombre'),
        'radiologos_opciones': [
            (u.id, u.get_full_name() or u.username)
            for u in Usuario.objects.filter(citas_asignadas__isnull=False).distinct().order_by('first_name', 'username')
        ],
        'medicos_opciones': MedicoTratante.objects.filter(citas__isnull=False).distinct().order_by('nombre').values_list('id', 'nombre'),
    }


COLUMNAS_CSV = ['Fecha', 'Hora', 'Paciente', 'Convenio', 'Estudio', 'Radiólogo', 'Médico tratante',
                'Horario', 'Estado del cobro', 'Forma de pago', 'Monto (Q)']


def escribir_csv(salida, citas):
    escritor = csv.writer(salida)
    escritor.writerow(COLUMNAS_CSV)
    for cita in citas:
        cobro = getattr(cita, 'cobro', None)
        if cita.convenio != Cita.CONVENIO_PRIVADO:
            estado_cobro, forma = 'Factura IGSS', ''
        elif cobro is not None and cobro.pagado:
            estado_cobro, forma = 'Cobrado', cobro.get_forma_pago_display()
        else:
            estado_cobro, forma = 'Pendiente', ''
        escritor.writerow([
            cita.fecha.strftime('%d/%m/%Y'), cita.hora.strftime('%H:%M'), str(cita.paciente),
            cita.get_convenio_display(), cita.tipo_estudio.nombre,
            (cita.radiologo.get_full_name() or cita.radiologo.username) if cita.radiologo_id else '',
            cita.medico_tratante.nombre if cita.medico_tratante_id else '',
            'Hábil' if es_horario_habil(cita.convenio, cita.hora) else 'Inhábil',
            estado_cobro, forma, f'{cita.precio_calculado:.2f}',
        ])
