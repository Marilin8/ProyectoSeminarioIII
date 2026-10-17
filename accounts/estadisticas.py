"""Estadísticas del panel del administrador.

Todo se calcula con los datos que el sistema ya guarda (no hace falta
migrar nada):

- Tiempo de atención por paciente: desde que recepción marca la llegada
  (`Cita.hora_llegada`) hasta que el técnico sube la última imagen del
  estudio (`ImagenEstudio.subida_en`), es decir, el tiempo que el paciente
  pasa en la clínica.
- Estudios realizados: citas en proceso o procesadas, por tipo de estudio.
- Pacientes nuevos: un paciente es "nuevo" en el mes de su primera cita
  (no rechazada); su origen es el convenio de esa primera cita.

Las gráficas se dibujan en el servidor (SVG/CSS, sin librerías de
JavaScript externas), así no dependen de un CDN ni chocan con la CSP.
"""
import datetime
from collections import defaultdict

from django.db.models import Count, Max
from django.utils import timezone

from pacientes.models import Cita, ImagenEstudio, InformeEstudio

from .models import Usuario

PERIODOS = (7, 30, 90)
PERIODO_POR_DEFECTO = 30
MESES_PACIENTES_NUEVOS = 6
MAX_ESTUDIOS_EN_GRAFICA = 8
# Tiempos fuera de este rango son errores de carga (llegada marcada otro día,
# imagen subida antes de la llegada) y desvirtúan el promedio.
MINUTOS_MINIMOS, MINUTOS_MAXIMOS = 1, 8 * 60
# El informe puede llegar días después de las imágenes; más de una semana se
# toma como dato erróneo (informe cargado sobre un estudio viejo).
MINUTOS_MAXIMOS_INFORME = 7 * 24 * 60

ESTADOS_REALIZADOS = (Cita.ESTADO_EN_PROCESO, Cita.ESTADO_PROCESADA)
CONVENIOS_IGSS = (Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS)
NOMBRES_MES = ('Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic')
COLORES_CONVENIO = {
    Cita.CONVENIO_PRIVADO: 'var(--morado-500)',
    Cita.CONVENIO_COEX: 'var(--cian-500)',
    Cita.CONVENIO_EMERGENCIA_IGSS: 'var(--cian-800)',
}

# Medidas del lienzo SVG de la gráfica de línea (en unidades del viewBox).
ANCHO, ALTO = 640, 220
MARGEN_IZQ, MARGEN_DER, MARGEN_SUP, MARGEN_INF = 40, 12, 12, 28


def periodo_valido(valor):
    try:
        dias = int(valor)
    except (TypeError, ValueError):
        return PERIODO_POR_DEFECTO
    return dias if dias in PERIODOS else PERIODO_POR_DEFECTO


def _minutos_de_atencion(desde, hasta):
    """{fecha: [minutos de cada paciente atendido ese día]}"""
    filas = (
        Cita.objects
        .filter(fecha__range=(desde, hasta), hora_llegada__isnull=False,
                orden_trabajo__imagenes__isnull=False)
        .annotate(fin=Max('orden_trabajo__imagenes__subida_en'))
        .values_list('fecha', 'hora_llegada', 'fin')
    )
    por_dia = defaultdict(list)
    for fecha, llegada, fin in filas:
        minutos = (fin - llegada).total_seconds() / 60
        if MINUTOS_MINIMOS <= minutos <= MINUTOS_MAXIMOS:
            por_dia[fecha].append(minutos)
    return por_dia


def _grafica_tiempos(por_dia, desde, dias):
    """Puntos de la gráfica de línea: promedio de minutos por día."""
    serie = []
    for i in range(dias):
        fecha = desde + datetime.timedelta(days=i)
        valores = por_dia.get(fecha, [])
        serie.append({
            'fecha': fecha,
            'promedio': round(sum(valores) / len(valores)) if valores else None,
            'pacientes': len(valores),
        })
    con_datos = [d['promedio'] for d in serie if d['promedio'] is not None]
    tope = max(con_datos, default=0)
    # Escala del eje Y en múltiplos de 20 minutos (mínimo 20): así las 4
    # divisiones caen en números enteros (0, 5, 10, 15, 20...).
    tope = max(20, -(-tope // 20) * 20)
    alto_util = ALTO - MARGEN_SUP - MARGEN_INF
    ancho_util = ANCHO - MARGEN_IZQ - MARGEN_DER
    paso = ancho_util / max(dias - 1, 1)

    puntos, tramos, tramo = [], [], []
    for i, dia in enumerate(serie):
        x = MARGEN_IZQ + i * paso
        if dia['promedio'] is None:
            if tramo:
                tramos.append(tramo)
            tramo = []
            continue
        y = MARGEN_SUP + alto_util * (1 - dia['promedio'] / tope)
        tramo.append(f'{x:.1f},{y:.1f}')
        puntos.append({**dia, 'x': round(x, 1), 'y': round(y, 1)})
    if tramo:
        tramos.append(tramo)

    lineas_y = []
    for k in range(5):
        valor = tope * k / 4
        lineas_y.append({'valor': round(valor), 'y': round(MARGEN_SUP + alto_util * (1 - valor / tope), 1)})
    # Etiquetas del eje X: unas 6, para que no se amontonen.
    cada = max(1, dias // 6)
    etiquetas_x = [
        {'x': round(MARGEN_IZQ + i * paso, 1), 'texto': serie[i]['fecha'].strftime('%d/%m')}
        for i in range(0, dias, cada)
    ]
    return {
        'ancho': ANCHO, 'alto': ALTO, 'x_inicio': MARGEN_IZQ, 'x_fin': ANCHO - MARGEN_DER,
        'y_base': ALTO - MARGEN_INF, 'y_texto_x': ALTO - 8,
        'tramos': [' '.join(t) for t in tramos], 'puntos': puntos,
        'lineas_y': lineas_y, 'etiquetas_x': etiquetas_x,
        'hay_datos': bool(puntos),
    }


def _estudios_realizados(desde, hasta):
    filas = list(
        Cita.objects
        .filter(fecha__range=(desde, hasta), estado__in=ESTADOS_REALIZADOS)
        .values('tipo_estudio__nombre')
        .annotate(total=Count('id'))
        .order_by('-total', 'tipo_estudio__nombre')
    )
    total = sum(f['total'] for f in filas)
    visibles = filas[:MAX_ESTUDIOS_EN_GRAFICA]
    otros = sum(f['total'] for f in filas[MAX_ESTUDIOS_EN_GRAFICA:])
    tope = visibles[0]['total'] if visibles else 0
    barras = [{
        'nombre': f['tipo_estudio__nombre'],
        'total': f['total'],
        'ancho': round(100 * f['total'] / tope, 1) if tope else 0,
        'porcentaje': round(100 * f['total'] / total) if total else 0,
    } for f in visibles]
    if otros:
        barras.append({
            'nombre': f'Otros ({len(filas) - MAX_ESTUDIOS_EN_GRAFICA} estudios)', 'total': otros,
            'ancho': round(100 * otros / tope, 1), 'porcentaje': round(100 * otros / total), 'otros': True,
        })
    return {'barras': barras, 'total': total, 'tipos': len(filas), 'top': barras[0] if barras else None}


def _por_convenio(desde, hasta):
    conteo = dict(
        Cita.objects
        .filter(fecha__range=(desde, hasta), estado__in=ESTADOS_REALIZADOS)
        .values_list('convenio')
        .annotate(total=Count('id'))
    )
    total = sum(conteo.values())
    segmentos, acumulado, partes_gradiente = [], 0.0, []
    for clave, nombre in Cita.CONVENIO_CHOICES:
        cantidad = conteo.get(clave, 0)
        porcentaje = 100 * cantidad / total if total else 0
        color = COLORES_CONVENIO[clave]
        if cantidad:
            partes_gradiente.append(f'{color} {acumulado:.2f}% {acumulado + porcentaje:.2f}%')
        acumulado += porcentaje
        segmentos.append({'nombre': nombre, 'total': cantidad, 'porcentaje': round(porcentaje), 'color': color})
    return {
        'segmentos': segmentos,
        'total': total,
        'gradiente': ', '.join(partes_gradiente) or 'var(--neutral-200) 0 100%',
    }


def _inicio_de_mes(fecha, meses_atras=0):
    año, mes = fecha.year, fecha.month - meses_atras
    while mes < 1:
        mes += 12
        año -= 1
    return datetime.date(año, mes, 1)


def _pacientes_nuevos(hoy):
    """Pacientes nuevos por mes (últimos MESES_PACIENTES_NUEVOS), privado vs. IGSS."""
    desde = _inicio_de_mes(hoy, MESES_PACIENTES_NUEVOS - 1)
    meses = [_inicio_de_mes(hoy, k) for k in range(MESES_PACIENTES_NUEVOS - 1, -1, -1)]
    conteo = {mes: {'privado': 0, 'igss': 0} for mes in meses}

    # Primera cita de cada paciente: recorrer en orden y quedarse con la primera.
    vistos = set()
    filas = (
        Cita.objects.exclude(estado=Cita.ESTADO_RECHAZADA)
        .order_by('paciente_id', 'fecha', 'hora', 'id')
        .values_list('paciente_id', 'fecha', 'convenio')
    )
    for paciente_id, fecha, convenio in filas.iterator():
        if paciente_id in vistos:
            continue
        vistos.add(paciente_id)
        if fecha < desde or fecha > hoy:
            continue
        grupo = 'igss' if convenio in CONVENIOS_IGSS else 'privado'
        conteo[_inicio_de_mes(fecha)][grupo] += 1

    tope = max((max(c.values()) for c in conteo.values()), default=0) or 1
    columnas = [{
        'mes': f'{NOMBRES_MES[mes.month - 1]} {mes:%y}',
        'privado': conteo[mes]['privado'],
        'igss': conteo[mes]['igss'],
        'alto_privado': round(100 * conteo[mes]['privado'] / tope, 1),
        'alto_igss': round(100 * conteo[mes]['igss'] / tope, 1),
    } for mes in meses]
    actual = columnas[-1]
    return {
        'columnas': columnas,
        'total_privado': sum(c['privado'] for c in columnas),
        'total_igss': sum(c['igss'] for c in columnas),
        'mes_actual': actual,
    }


def formato_duracion(minutos):
    minutos = round(minutos)
    if minutos < 60:
        return f'{minutos} min'
    horas, resto = divmod(minutos, 60)
    if horas < 24:
        return f'{horas} h {resto} min' if resto else f'{horas} h'
    dias, horas = divmod(horas, 24)
    return f'{dias} d {horas} h' if horas else f'{dias} d'


def _ranking(minutos_por_persona):
    """Filas ordenadas de la más rápida a la más lenta para la gráfica."""
    nombres = {
        u.id: u.get_full_name() or u.username
        for u in Usuario.objects.filter(id__in=[k for k in minutos_por_persona if k])
    }
    filas = []
    for persona_id, valores in minutos_por_persona.items():
        promedio = sum(valores) / len(valores)
        filas.append({
            'nombre': nombres.get(persona_id, 'Sin registrar'),
            'pacientes': len(valores),
            'minutos': round(promedio),
            'texto': formato_duracion(promedio),
        })
    filas.sort(key=lambda f: (f['minutos'], f['nombre']))
    tope = max((f['minutos'] for f in filas), default=0) or 1
    for f in filas:
        f['ancho'] = max(round(100 * f['minutos'] / tope, 1), 2)
    if len(filas) > 1:
        filas[0]['etiqueta'] = 'rapido'
        filas[-1]['etiqueta'] = 'lento'
    return filas


def _tiempos_por_personal(desde, hasta):
    """Quién atendió y cuánto tardó, en el periodo:

    - Técnico: el que subió la primera imagen del estudio (el mismo criterio
      que el reporte diario, ver Cita.tecnico_asignado); se mide desde la
      llegada del paciente hasta la última imagen subida.
    - Radiólogo: el que cargó el informe; se mide desde la última imagen
      hasta el último informe del estudio (en combos hay uno por estudio).
    """
    imagenes = (
        ImagenEstudio.objects
        .filter(orden__cita__fecha__range=(desde, hasta))
        .order_by('subida_en', 'id')
        .values_list('orden_id', 'orden__cita__hora_llegada', 'subida_en', 'subida_por_id')
    )
    por_orden = {}
    for orden_id, llegada, subida_en, subida_por in imagenes:
        datos = por_orden.setdefault(orden_id, {'llegada': llegada, 'tecnico': subida_por})
        datos['ultima'] = subida_en

    tecnicos = defaultdict(list)
    for datos in por_orden.values():
        if datos['llegada'] is None:
            continue
        minutos = (datos['ultima'] - datos['llegada']).total_seconds() / 60
        if MINUTOS_MINIMOS <= minutos <= MINUTOS_MAXIMOS:
            tecnicos[datos['tecnico']].append(minutos)

    informes = (
        InformeEstudio.objects
        .filter(orden__cita__fecha__range=(desde, hasta), creado_en__isnull=False)
        .order_by('creado_en', 'id')
        .values_list('orden_id', 'creado_en', 'creado_por_id', 'orden__cita__radiologo_id')
    )
    ultimo_informe = {}
    for orden_id, creado_en, creado_por, radiologo in informes:
        ultimo_informe[orden_id] = (creado_en, creado_por or radiologo)

    radiologos = defaultdict(list)
    for orden_id, (creado_en, radiologo) in ultimo_informe.items():
        imagenes_listas = por_orden.get(orden_id, {}).get('ultima')
        if imagenes_listas is None:
            continue
        minutos = (creado_en - imagenes_listas).total_seconds() / 60
        if MINUTOS_MINIMOS <= minutos <= MINUTOS_MAXIMOS_INFORME:
            radiologos[radiologo].append(minutos)

    return {'tecnicos': _ranking(tecnicos), 'radiologos': _ranking(radiologos)}


def calcular(dias=PERIODO_POR_DEFECTO, hoy=None):
    hoy = hoy or timezone.localdate()
    dias = periodo_valido(dias)
    desde = hoy - datetime.timedelta(days=dias - 1)

    minutos = _minutos_de_atencion(desde, hoy)
    todos = [m for valores in minutos.values() for m in valores]
    de_hoy = minutos.get(hoy, [])
    estudios = _estudios_realizados(desde, hoy)

    return {
        'dias': dias,
        'periodos': PERIODOS,
        'desde': desde,
        'hoy': hoy,
        'kpi': {
            'atendidos_hoy': Cita.objects.filter(fecha=hoy, estado__in=ESTADOS_REALIZADOS).count(),
            'promedio_hoy': round(sum(de_hoy) / len(de_hoy)) if de_hoy else None,
            'promedio_periodo': round(sum(todos) / len(todos)) if todos else None,
            'pacientes_medidos': len(todos),
        },
        'tiempos': _grafica_tiempos(minutos, desde, dias),
        'personal': _tiempos_por_personal(desde, hoy),
        'estudios': estudios,
        'convenios': _por_convenio(desde, hoy),
        'nuevos': _pacientes_nuevos(hoy),
    }
