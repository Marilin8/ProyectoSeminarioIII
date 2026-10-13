"""Panel "Estado de la Clínica" del administrador: dashboards con la marcha de
la clínica (citas por estado, tiempos, estudios más frecuentes, respuesta de
los radiólogos en COEX y esperas por urgencia).

Todo se calcula en Python a partir de consultas por rango de fechas (no con
`__date`, que en el MySQL local sin tablas de zona horaria devuelve vacío; ver
Ticket.del_dia).
"""
import datetime
from collections import Counter, defaultdict

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.views import es_administrador

from .models import Cita, InformeEstudio, OrdenTrabajo, Ticket

PERIODOS = (
    (1, 'Hoy'),
    (7, '7 días'),
    (30, '30 días'),
    (90, '90 días'),
    (365, '1 año'),
)
DIAS_POR_DEFECTO = 30
TOP_ESTUDIOS = 8

CONVENIOS = (
    ('', 'Todos los convenios'),
    (Cita.CONVENIO_COEX, 'COEX'),
    (Cita.CONVENIO_PRIVADO, 'Privado'),
    (Cita.CONVENIO_EMERGENCIA_IGSS, 'Emergencia IGSS'),
)


def _minutos(delta):
    return delta.total_seconds() / 60


def _promedio(valores):
    return round(sum(valores) / len(valores), 1) if valores else 0


def _dias_validos(texto):
    try:
        dias = int(texto)
    except (TypeError, ValueError):
        return DIAS_POR_DEFECTO
    return dias if dias in dict(PERIODOS) else DIAS_POR_DEFECTO


def _convenio_valido(texto):
    return texto if texto in dict(CONVENIOS) else ''


def _rango_datetimes(inicio, fin):
    """[inicio, fin] (fechas locales, inclusive) como datetimes con zona."""
    desde = timezone.make_aware(datetime.datetime.combine(inicio, datetime.time.min))
    hasta = timezone.make_aware(
        datetime.datetime.combine(fin + datetime.timedelta(days=1), datetime.time.min)
    )
    return desde, hasta


def _citas_por_estado(citas, convenio, hoy):
    conteo = Counter(citas.values_list('estado', flat=True))
    futuras = Cita.objects.filter(
        fecha__gt=hoy, estado__in=(Cita.ESTADO_AGENDADA, Cita.ESTADO_EN_ESPERA),
    )
    if convenio:
        futuras = futuras.filter(convenio=convenio)
    return {
        # "Aprobadas": ya confirmadas/agendadas y todavía sin atender.
        'aprobadas': conteo[Cita.ESTADO_AGENDADA] + conteo[Cita.ESTADO_EN_ESPERA],
        'en_proceso': conteo[Cita.ESTADO_EN_PROCESO],
        'pendientes': conteo[Cita.ESTADO_PENDIENTE],
        'completadas': conteo[Cita.ESTADO_PROCESADA],
        'rechazadas': conteo[Cita.ESTADO_RECHAZADA],
        'ausentes': conteo[Cita.ESTADO_AUSENTE],
        'futuras_agendadas': futuras.count(),
        'total': sum(conteo.values()),
    }


def _tiempo_por_cita(citas_procesadas):
    """Por tipo de estudio: duración estimada (la configurada en el
    estudio) y el ciclo real -- desde que se genera la orden de trabajo hasta
    el último informe subido (incluye la espera del informe de la radióloga)."""
    citas = list(citas_procesadas.select_related('tipo_estudio'))
    ordenes = dict(
        OrdenTrabajo.objects.filter(cita__in=[c.id for c in citas])
        .values_list('cita_id', 'creada_en')
    )
    ordenes_ids = dict(
        OrdenTrabajo.objects.filter(cita__in=[c.id for c in citas]).values_list('id', 'cita_id')
    )
    ultimo_informe = {
        fila['orden_id']: fila['ultimo']
        for fila in InformeEstudio.objects.filter(
            orden_id__in=list(ordenes_ids), creado_en__isnull=False,
        ).values('orden_id').annotate(ultimo=Max('creado_en'))
    }
    ciclos_por_cita = {}
    for orden_id, cita_id in ordenes_ids.items():
        inicio, fin = ordenes.get(cita_id), ultimo_informe.get(orden_id)
        if inicio and fin and fin >= inicio:
            ciclos_por_cita[cita_id] = _minutos(fin - inicio)

    por_estudio = defaultdict(lambda: {'nombre': '', 'estimada': 0, 'ciclos': [], 'cantidad': 0})
    for cita in citas:
        datos = por_estudio[cita.tipo_estudio_id]
        datos['nombre'] = cita.tipo_estudio.nombre
        datos['estimada'] = cita.tipo_estudio.duracion_minutos
        datos['cantidad'] += 1
        if cita.id in ciclos_por_cita:
            datos['ciclos'].append(ciclos_por_cita[cita.id])

    top = sorted(por_estudio.values(), key=lambda d: -d['cantidad'])[:TOP_ESTUDIOS]
    return {
        'labels': [d['nombre'] for d in top],
        'estimada': [d['estimada'] for d in top],
        'real': [_promedio(d['ciclos']) for d in top],
        'estimada_promedio': _promedio([c.tipo_estudio.duracion_minutos for c in citas]),
        'ciclo_promedio': _promedio(list(ciclos_por_cita.values())),
    }


def _frecuencia_estudios(citas_procesadas, dias):
    conteo = Counter(citas_procesadas.values_list('tipo_estudio__nombre', flat=True))
    top = conteo.most_common(TOP_ESTUDIOS)
    total = sum(conteo.values())
    return {
        'labels': [nombre for nombre, _ in top],
        'valores': [cantidad for _, cantidad in top],
        'total': total,
        'distintos': len(conteo),
        'promedio_diario': round(total / dias, 1),
        'promedio_semanal': round(total / dias * 7, 1),
    }


def _respuesta_radiologos(desde, hasta):
    """Cuánto tarda cada radiólogo en responder (aceptar o rechazar) una
    solicitud de COEX: desde que recepción la crea hasta que la revisa."""
    solicitudes = Cita.objects.filter(
        convenio=Cita.CONVENIO_COEX, revisada_en__isnull=False, revisada_por__isnull=False,
        creada_en__gte=desde, creada_en__lt=hasta,
    ).select_related('revisada_por')
    por_radiologo = defaultdict(lambda: {'nombre': '', 'tiempos': [], 'rechazadas': 0})
    todos = []
    for cita in solicitudes:
        radiologo = cita.revisada_por
        datos = por_radiologo[radiologo.id]
        datos['nombre'] = radiologo.get_full_name() or radiologo.username
        minutos = max(_minutos(cita.revisada_en - cita.creada_en), 0)
        datos['tiempos'].append(minutos)
        todos.append(minutos)
        if cita.estado == Cita.ESTADO_RECHAZADA:
            datos['rechazadas'] += 1
    filas = sorted(por_radiologo.values(), key=lambda d: _promedio(d['tiempos']))
    return {
        'labels': [d['nombre'] for d in filas],
        'promedio_min': [_promedio(d['tiempos']) for d in filas],
        'solicitudes': [len(d['tiempos']) for d in filas],
        'rechazadas': [d['rechazadas'] for d in filas],
        'promedio_global': _promedio(todos),
        'total': len(todos),
    }


def _espera_por_urgencia(desde, hasta, convenio):
    """Tiempo que espera cada paciente en la fila (turno creado -> atendido),
    según la urgencia (prioridad) del turno."""
    tickets = Ticket.objects.filter(
        estado=Ticket.ESTADO_ATENDIDO, atendido_en__isnull=False,
        creado_en__gte=desde, creado_en__lt=hasta,
    )
    if convenio:
        tickets = tickets.filter(servicio=convenio)
    por_prioridad = defaultdict(list)
    for creado, atendido, prioridad in tickets.values_list('creado_en', 'atendido_en', 'prioridad'):
        por_prioridad[prioridad].append(max(_minutos(atendido - creado), 0))
    etiquetas = dict(Ticket.PRIORIDAD_CHOICES)
    prioridades = [Ticket.PRIORIDAD_NORMAL, Ticket.PRIORIDAD_URGENTE, Ticket.PRIORIDAD_CRITICA]
    return {
        'labels': [etiquetas[p] for p in prioridades],
        'promedio': [_promedio(por_prioridad[p]) for p in prioridades],
        'maximo': [round(max(por_prioridad[p]), 1) if por_prioridad[p] else 0 for p in prioridades],
        'atendidos': [len(por_prioridad[p]) for p in prioridades],
        'total': sum(len(v) for v in por_prioridad.values()),
    }


def calcular_estado_clinica(dias=DIAS_POR_DEFECTO, convenio=''):
    hoy = timezone.localdate()
    inicio = hoy - datetime.timedelta(days=dias - 1)
    desde, hasta = _rango_datetimes(inicio, hoy)

    citas = Cita.objects.filter(fecha__gte=inicio, fecha__lte=hoy)
    if convenio:
        citas = citas.filter(convenio=convenio)
    procesadas = citas.filter(estado=Cita.ESTADO_PROCESADA)

    return {
        'periodo': {
            'dias': dias, 'desde': inicio.isoformat(), 'hasta': hoy.isoformat(),
            'actualizado': timezone.localtime().strftime('%H:%M:%S'),
        },
        'citas': _citas_por_estado(citas, convenio, hoy),
        'tiempo_por_cita': _tiempo_por_cita(procesadas),
        'frecuencia': _frecuencia_estudios(procesadas, dias),
        'radiologos': _respuesta_radiologos(desde, hasta),
        'espera': _espera_por_urgencia(desde, hasta, convenio),
    }


@login_required
@user_passes_test(es_administrador)
def estado_clinica(request):
    return render(request, 'pacientes/estado_clinica.html', {
        'periodos': PERIODOS,
        'convenios': CONVENIOS,
        'dias': _dias_validos(request.GET.get('dias')),
        'convenio': _convenio_valido(request.GET.get('convenio', '')),
    })


@login_required
@user_passes_test(es_administrador)
def estado_clinica_datos(request):
    """JSON que consume el panel para refrescar las gráficas sin recargar."""
    return JsonResponse(calcular_estado_clinica(
        dias=_dias_validos(request.GET.get('dias')),
        convenio=_convenio_valido(request.GET.get('convenio', '')),
    ))
