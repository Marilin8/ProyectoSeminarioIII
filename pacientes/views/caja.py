"""Caja: cobros, órdenes de pago agrupadas, boletas/constancias en PDF y pagos IGSS.
"""
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts import sucursales
from accounts.models import Bitacora

from ..forms import CrearOrdenPagoForm, RegistrarPagoEstudioForm, SubirConstanciaFirmadaForm
from ..models import (
    PREFETCH_PRECIO_CITA,
    Cita,
    Cobro,
    Combo,
    DetalleOrdenPago,
    OrdenPago,
    OrdenTrabajo,
    TipoEstudio,
)
from .citas import _volver_seguro
from .comun import CLINICA_DIRECCION, CLINICA_NOMBRE, CLINICA_RUBRO, CLINICA_TELEFONO
from .envio_resultados import _intentar_envio_automatico
from .permisos import es_caja, puede_ver_comprobante_pago


# --- Caja: cobro de estudios ----------------------------------------------
#
# Cobro es opcional y solo administrativo: registra si ya se cobró el
# estudio (recepción/caja lo marcan a mano), no mueve dinero real. Mientras
# quede pendiente, bloquea el envío de resultados al paciente (ver
# _cobro_bloquea_envio) pero no afecta el trabajo del técnico ni del
# radiólogo. Portado (2026-09-04) desde la rama visual-andres de TechBlood.

@login_required
@user_passes_test(es_caja)
def pagos_pendientes_igss(request):
    """Pantalla "Pagos IGSS": COEX y Emergencia IGSS se cobran solo por orden
    agrupada. La orden la definen dos datos: el monto máximo (se agrupan los
    estudios pendientes de la más antigua a la más reciente mientras quepan)
    y, opcionalmente, un tipo de estudio y/o un código IGSS. Al crearla, los
    estudios quedan agrupados en una orden pendiente de comprobante; recién
    cuando se sube la boleta pasan a pagados (ver crear_orden_pago/
    pagar_orden_pago)."""
    convenios_igss = (Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS)
    convenio = request.GET.get('convenio', '')
    tipo_estudio = request.GET.get('tipo_estudio', '')
    codigo_igss = (request.GET.get('codigo_igss') or '').strip()
    try:
        monto_maximo = Decimal((request.GET.get('monto_maximo') or '').replace(',', '.') or '0')
    except ArithmeticError:
        monto_maximo = Decimal('0')
    if monto_maximo < 0:
        monto_maximo = Decimal('0')

    previa = None
    if convenio in convenios_igss:
        candidatas = _citas_pendientes_para_orden(
            convenio,
            tipo_estudio_id=int(tipo_estudio) if tipo_estudio.isdigit() else None,
            codigo_igss=codigo_igss, request=request,
        )
        incluidas, fuera = _citas_hasta_monto(candidatas, monto_maximo or None)
        previa = {
            'citas': incluidas,
            'cantidad': len(incluidas),
            'pacientes': len({c.paciente_id for c in incluidas}),
            'total': _total_citas_para_orden(incluidas),
            'fuera_cantidad': len(fuera),
            'fuera_total': _total_citas_para_orden(fuera),
        }

    ordenes = sucursales.filtrar(
        OrdenPago.objects.filter(convenio__in=convenios_igss), request, 'detalles__cita__sucursal',
    ).distinct().select_related('creado_por')
    pendientes = ordenes.filter(estado=OrdenPago.ESTADO_PENDIENTE).prefetch_related('detalles').order_by('-creado_en')
    pagadas = ordenes.filter(estado=OrdenPago.ESTADO_PAGADA).prefetch_related('detalles').order_by('-pagado_en')[:15]

    sin_agrupar = [c for conv in convenios_igss for c in _citas_pendientes_para_orden(conv, request=request)]

    return render(request, 'pacientes/pagos_igss.html', {
        'convenios': [(v, dict(Cita.CONVENIO_CHOICES)[v]) for v in convenios_igss],
        'tipos_estudio': TipoEstudio.objects.filter(activo=True).order_by('nombre'),
        'convenio': convenio,
        'tipo_estudio': tipo_estudio,
        'codigo_igss': codigo_igss,
        'monto_maximo': monto_maximo or '',
        'previa': previa,
        'pendientes': pendientes,
        'pagadas': pagadas,
        'total_pendiente': sum((o.total for o in pendientes), Decimal('0.00')),
        'sin_agrupar_cantidad': len(sin_agrupar),
        'sin_agrupar_total': _total_citas_para_orden(sin_agrupar),
    })


@login_required
@user_passes_test(es_caja)
def pagos_pendientes(request):
    """Listado paginado de cobros, con filtros para Caja."""
    qs = sucursales.filtrar(Cobro.objects, request, 'cita__sucursal').select_related(
        'cita__paciente', 'cita__tipo_estudio', 'cita__orden_trabajo', 'cita__sucursal', 'cobrado_por',
    ).prefetch_related(*(f'cita__{r}' for r in PREFETCH_PRECIO_CITA)).order_by('-creado_en')
    busqueda = (request.GET.get('q') or '').strip()
    estado = request.GET.get('estado', Cobro.ESTADO_PENDIENTE)
    convenio = request.GET.get('convenio', '')
    tipo_estudio = request.GET.get('tipo_estudio', '')
    combo_id = request.GET.get('combo', '')
    desde = parse_date(request.GET.get('desde', ''))
    hasta = parse_date(request.GET.get('hasta', ''))
    if busqueda:
        qs = qs.filter(
            Q(cita__paciente__nombre__icontains=busqueda)
            | Q(cita__paciente__apellido__icontains=busqueda)
            | Q(cita__paciente__dpi__icontains=busqueda)
        )
    if estado in (Cobro.ESTADO_PENDIENTE, Cobro.ESTADO_PAGADO):
        qs = qs.filter(estado=estado)
    if convenio == Cita.CONVENIO_EMERGENCIA_IGSS:
        # "Pagos IGSS" es el único lugar donde se cobran COEX y Emergencia
        # IGSS: ambos se pagan por orden agrupada (nunca por estudio suelto),
        # así que se muestran juntos acá.
        qs = qs.filter(cita__convenio__in=(Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS))
    elif convenio in dict(Cita.CONVENIO_CHOICES):
        qs = qs.filter(cita__convenio=convenio)
    else:
        # Vista general sin filtro de convenio: COEX y Emergencia IGSS no se
        # cobran estudio por estudio desde acá (no tienen botón de "Marcar
        # pagado", ver template), solo desde "Pagos IGSS".
        qs = qs.exclude(cita__convenio__in=(Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS))
    if tipo_estudio.isdigit():
        qs = qs.filter(cita__tipo_estudio_id=int(tipo_estudio))
    if desde:
        qs = qs.filter(cita__fecha__gte=desde)
    if hasta:
        qs = qs.filter(cita__fecha__lte=hasta)
    if combo_id.isdigit():
        qs = qs.filter(
            cita__detalles_orden_pago__orden_pago__combo_id=int(combo_id),
        ).distinct()

    # Vista previa de "Crear orden agrupada": convenio + rango de fechas
    # elegidos en ese formulario aparte (no los filtros de arriba, que son
    # para mirar la lista, no para armar la orden). Solo se calcula cuando
    # los tres datos están completos, para no barrer sin querer todo el
    # historial pendiente de un convenio.
    orden_convenio = request.GET.get('orden_convenio', '')
    orden_desde = parse_date(request.GET.get('orden_desde', ''))
    orden_hasta = parse_date(request.GET.get('orden_hasta', ''))
    resumen_orden_rango = None
    if orden_convenio in (Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS) and orden_desde and orden_hasta:
        citas_rango = _citas_pendientes_para_orden(orden_convenio, orden_desde, orden_hasta, request=request)
        resumen_orden_rango = {
            'cantidad': len(citas_rango),
            'pacientes': len({c.paciente_id for c in citas_rango}),
            'total': _total_citas_para_orden(citas_rango),
        }

    # Solo entran a una orden agrupada los estudios que el técnico ya
    # confirmó como correctos (ver OrdenTrabajo.validacion_estado).
    cobros_para_orden = qs.filter(
        estado=Cobro.ESTADO_PENDIENTE,
        cita__convenio__in=(Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS),
        cita__orden_trabajo__validacion_estado=OrdenTrabajo.VALIDACION_CORRECTO,
    ).select_related('cita__paciente', 'cita__tipo_estudio')
    pagina = Paginator(qs, 20).get_page(request.GET.get('page'))

    filtros = request.GET.copy()
    filtros.pop('page', None)
    ordenes_pago = sucursales.filtrar(
        OrdenPago.objects, request, 'detalles__cita__sucursal',
    ).distinct().select_related(
        'paciente', 'creado_por', 'combo',
    ).prefetch_related('detalles__tipo_estudio').filter(
        estado=OrdenPago.ESTADO_PENDIENTE,
    )
    if convenio == Cita.CONVENIO_EMERGENCIA_IGSS:
        ordenes_pago = ordenes_pago.filter(
            convenio__in=(Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS),
        )
    elif convenio == Cita.CONVENIO_COEX:
        ordenes_pago = ordenes_pago.filter(convenio=convenio)
    if combo_id.isdigit():
        ordenes_pago = ordenes_pago.filter(combo_id=int(combo_id))
    combos = Combo.objects.filter(activo=True).prefetch_related('estudios').order_by('nombre')
    return render(request, 'pacientes/pagos_pendientes.html', {
        'pagina': pagina,
        'cobros_para_orden': cobros_para_orden,
        'busqueda': busqueda,
        'estado': estado,
        'convenio': convenio,
        'tipo_estudio': tipo_estudio,
        'combo_id': combo_id,
        'desde': desde,
        'hasta': hasta,
        'convenios': Cita.CONVENIO_CHOICES,
        'tipos_estudio': TipoEstudio.objects.filter(activo=True).order_by('nombre'),
        'filtros_qs': filtros.urlencode(),
        'ordenes_pago': ordenes_pago[:20],
        'combos': combos,
        'orden_convenio': orden_convenio,
        'orden_desde': orden_desde,
        'orden_hasta': orden_hasta,
        'resumen_orden_rango': resumen_orden_rango,
    })


def _citas_pendientes_para_orden(
    convenio, desde=None, hasta=None, *, tipo_estudio_id=None, codigo_igss='', para_actualizar=False,
    request=None,
):
    """Citas de `convenio` listas para agruparse en una orden de pago: el
    técnico ya confirmó el estudio, tienen cobro pendiente y no están ya en
    otra orden agrupada abierta. Opcionalmente solo entre `desde` y `hasta`
    (inclusive), solo de un tipo de estudio, y/o solo con un código IGSS
    puntual. Las más antiguas primero. No importa de qué paciente sean --
    una orden agrupada cubre el convenio elegido, no una sola visita."""
    qs = Cita.objects.filter(
        convenio=convenio,
        orden_trabajo__validacion_estado=OrdenTrabajo.VALIDACION_CORRECTO,
        cobro__estado=Cobro.ESTADO_PENDIENTE,
    ).exclude(
        detalles_orden_pago__orden_pago__estado=OrdenPago.ESTADO_PENDIENTE,
    ).select_related('paciente', 'tipo_estudio', 'sucursal').prefetch_related(
        *PREFETCH_PRECIO_CITA,
    ).order_by('fecha', 'hora', 'id')
    if desde:
        qs = qs.filter(fecha__gte=desde)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    if tipo_estudio_id:
        qs = qs.filter(tipo_estudio_id=tipo_estudio_id)
    if codigo_igss:
        qs = qs.filter(codigo_igss__iexact=codigo_igss)
    if request is not None:
        qs = sucursales.filtrar(qs, request)  # solo la sucursal activa
    if para_actualizar:
        qs = qs.select_for_update()
    return list(qs)


def _total_cita_para_orden(cita):
    """Precio base de la cita más los estudios extra que sí se cobran."""
    total = cita.precio_base
    for extra in cita.estudios_extra_cobrados:
        total += extra.precio
    return total


def _total_citas_para_orden(citas):
    """Suma de ``_total_cita_para_orden`` para varias citas (Decimal)."""
    return sum((_total_cita_para_orden(c) for c in citas), Decimal('0.00'))


def _citas_hasta_monto(citas, monto_maximo):
    """Reparte `citas` (ya ordenadas de la más antigua a la más reciente) en
    (incluidas, excluidas): entran en orden mientras el acumulado no pase de
    `monto_maximo`; en la primera que ya no cabe se corta (no se saltea para
    meter una más barata, así nunca queda un estudio viejo atrás de uno más
    nuevo). Sin monto máximo entran todas."""
    if not monto_maximo:
        return list(citas), []
    incluidas, acumulado = [], Decimal('0.00')
    for posicion, cita in enumerate(citas):
        total = _total_cita_para_orden(cita)
        if acumulado + total > monto_maximo:
            return incluidas, list(citas[posicion:])
        incluidas.append(cita)
        acumulado += total
    return incluidas, []


@login_required
@user_passes_test(es_caja)
@require_POST
def crear_orden_pago(request):
    """Agrupa TODOS los estudios pendientes de cobro de un convenio (COEX o
    Emergencia IGSS) dentro de un rango de fechas en una sola orden de
    pago -- por ejemplo, la liquidación semanal de un convenio
    institucional que cubre decenas de pacientes distintos. No exige que
    los estudios sean del mismo paciente: el único requisito compartido es
    el convenio."""
    form = CrearOrdenPagoForm(request.POST)
    if not form.is_valid():
        for error in form.non_field_errors():
            messages.error(request, error)
        if not form.non_field_errors():
            messages.error(request, 'Revisá el convenio y los criterios de la orden.')
        return redirect(_volver_seguro(request, reverse('pagos_pendientes')))

    convenio = form.cleaned_data['convenio']
    desde = form.cleaned_data['desde']
    hasta = form.cleaned_data['hasta']
    monto_maximo = form.cleaned_data['monto_maximo']
    tipo_filtro = form.cleaned_data['tipo_estudio']
    codigo_igss = form.cleaned_data['codigo_igss']

    with transaction.atomic():
        candidatas = _citas_pendientes_para_orden(
            convenio, desde, hasta,
            tipo_estudio_id=tipo_filtro.id if tipo_filtro else None,
            codigo_igss=codigo_igss, para_actualizar=True, request=request,
        )
        citas, _fuera = _citas_hasta_monto(candidatas, monto_maximo)
        if not citas:
            messages.error(
                request,
                'No hay estudios pendientes de cobro que cumplan esos criterios'
                + (' dentro del monto máximo.' if monto_maximo and candidatas else '.'),
            )
            return redirect(_volver_seguro(request, reverse('pagos_pendientes')))

        detalles = []
        subtotal = Decimal('0.00')
        for cita in citas:
            precio = cita.precio_base
            detalles.append((cita, cita.tipo_estudio, None, precio))
            subtotal += precio
            for extra in cita.estudios_extra_cobrados:
                precio_extra = extra.precio
                detalles.append((cita, extra.tipo_estudio, extra, precio_extra))
                subtotal += precio_extra

        pacientes_distintos = {c.paciente_id for c in citas}
        criterios = [dict(Cita.CONVENIO_CHOICES).get(convenio, convenio)]
        if desde and hasta:
            criterios.append(f'del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}')
        if tipo_filtro:
            criterios.append(tipo_filtro.nombre)
        if codigo_igss:
            criterios.append(f'código {codigo_igss}')
        if monto_maximo:
            criterios.append(f'máx. Q{monto_maximo:.2f}')
        notas = form.cleaned_data['notas'] or ' · '.join(criterios)
        orden = OrdenPago.objects.create(
            convenio=convenio,
            paciente=citas[0].paciente if len(pacientes_distintos) == 1 else None,
            subtotal=subtotal,
            descuento=Decimal('0.00'),
            total=subtotal,
            combo=None,
            notas=notas,
            creado_por=request.user,
        )
        for cita, tipo, extra, precio in detalles:
            DetalleOrdenPago.objects.create(
                orden_pago=orden,
                cita=cita,
                tipo_estudio=tipo,
                estudio_extra=extra,
                precio=precio,
                descuento=Decimal('0.00'),
                total=precio,
            )

    messages.success(
        request,
        f'Orden de pago #{orden.id} creada: {len(citas)} estudio{"s" if len(citas) != 1 else ""} '
        f'de {len(pacientes_distintos)} paciente{"s" if len(pacientes_distintos) != 1 else ""}, '
        f'total Q{subtotal:.2f}.',
    )
    return redirect(_volver_seguro(request, reverse('pagos_pendientes')))


@login_required
@user_passes_test(es_caja)
@require_POST
def pagar_orden_pago(request, orden_id):
    """Adjunta la boleta global y liquida todos los estudios de la orden."""
    orden = get_object_or_404(
        sucursales.permitidas(OrdenPago.objects.prefetch_related('detalles__cita'), request.user, 'detalles__cita__sucursal'),
        id=orden_id,
        estado=OrdenPago.ESTADO_PENDIENTE,
    )
    form = RegistrarPagoEstudioForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'Adjunte una boleta válida y complete los datos del pago.')
        return redirect(_volver_seguro(request, reverse('pagos_pendientes')))
    if not form.cleaned_data['comprobante_bancario']:
        messages.error(request, 'La orden agrupada requiere adjuntar la boleta global.')
        return redirect(_volver_seguro(request, reverse('pagos_pendientes')))

    with transaction.atomic():
        orden.numero_boleta = form.cleaned_data['numero_boleta']
        orden.comprobante_bancario = form.cleaned_data['comprobante_bancario']
        orden.estado = OrdenPago.ESTADO_PAGADA
        orden.pagado_por = request.user
        orden.pagado_en = timezone.now()
        orden.save(update_fields=[
            'numero_boleta', 'comprobante_bancario', 'estado', 'pagado_por', 'pagado_en',
        ])
        citas_pagadas = []
        for detalle in orden.detalles.select_related('cita'):
            cobro, _ = Cobro.objects.get_or_create(cita=detalle.cita)
            cobro.forma_pago = form.cleaned_data['forma_pago']
            cobro.numero_boleta = orden.numero_boleta
            cobro.comprobante_bancario = orden.comprobante_bancario.name
            cobro.marcar_pagado(request.user, notas=form.cleaned_data['notas'])
            citas_pagadas.append(detalle.cita)

    messages.success(request, f'Orden de pago #{orden.id} confirmada y estudios liberados.')
    for cita in citas_pagadas:
        _intentar_envio_automatico(request, cita)
    return redirect(_volver_seguro(request, reverse('pagos_pendientes')))


@login_required
@user_passes_test(es_caja)
def orden_pago_pdf(request, orden_id):
    """Listado imprimible de una orden de pago agrupada: una fila por
    estudio (paciente, DPI, estudio, precio) y el total general. A
    diferencia de la boleta de un cobro individual (armada para un solo
    paciente), esta orden suele cubrir muchos pacientes distintos del
    mismo convenio en un rango de fechas, así que el comprobante es un
    listado en vez de un recibo por paciente."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    orden = get_object_or_404(
        sucursales.permitidas(OrdenPago.objects.prefetch_related('detalles__cita__paciente', 'detalles__tipo_estudio'), request.user, 'detalles__cita__sucursal'),
        id=orden_id,
    )
    detalles = list(orden.detalles.all())
    pacientes_distintos = len({d.cita.paciente_id for d in detalles})

    azul = colors.HexColor('#1d3a8a')
    gris = colors.HexColor('#cbd5e1')

    base = getSampleStyleSheet()['BodyText']
    base.fontSize = 9
    base.leading = 13
    negrita = {'parent': base, 'fontName': 'Helvetica-Bold'}
    st_titulo = ParagraphStyle('titulo', fontSize=13, alignment=TA_CENTER, **negrita)
    st_derecha = ParagraphStyle('derecha', parent=base, alignment=TA_RIGHT)

    filas = [['Paciente', 'DPI', 'Estudio', 'Precio']]
    for detalle in detalles:
        paciente = detalle.cita.paciente
        filas.append([
            f'{paciente.nombre} {paciente.apellido}',
            paciente.dpi,
            detalle.tipo_estudio.nombre,
            f'Q{detalle.total:.2f}',
        ])
    filas.append(['', '', 'Total:', f'Q{orden.total:.2f}'])

    tabla = Table(filas, colWidths=[5.5 * cm, 3.2 * cm, 5.5 * cm, 3.0 * cm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), azul),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (2, -1), (3, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, -2), (3, -2), 'Helvetica-Bold'),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, gris),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
    ]))

    elementos = [
        Paragraph(
            f'<b>{CLINICA_NOMBRE}</b><br/>{CLINICA_RUBRO}<br/>'
            f'Dirección: {CLINICA_DIRECCION}<br/>Tel: {CLINICA_TELEFONO}',
            base,
        ),
        Spacer(1, 14),
        Paragraph('LISTADO DE ORDEN DE PAGO AGRUPADA', st_titulo),
        Spacer(1, 4),
        Paragraph(f'N.º de orden: {orden.id} — {orden.get_estado_display()}', st_derecha),
        Spacer(1, 10),
        Paragraph(
            f'<b>Convenio:</b> {orden.get_convenio_display()}<br/>'
            f'<b>Notas:</b> {orden.notas or "—"}<br/>'
            f'<b>Cantidad de estudios:</b> {len(detalles)}<br/>'
            f'<b>Pacientes distintos:</b> {pacientes_distintos}',
            base,
        ),
        Spacer(1, 14),
        tabla,
    ]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm, title=f'Orden de pago {orden.id}',
    )
    doc.build(elementos)

    respuesta = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    respuesta['Content-Disposition'] = f'inline; filename="orden_pago_{orden.id}.pdf"'
    return respuesta


def datos_paciente_boleta(cita):
    """Filas (etiqueta, valor) de los datos del paciente que salen en la
    boleta de pago. En estudios del convenio Privado NO se incluye el carné
    del IGSS (esos pacientes no necesariamente están afiliados)."""
    paciente = cita.paciente
    filas = [
        ('Expediente:', paciente.expediente or 'No asignado'),
        ('DPI:', paciente.dpi or 'No registrado'),
    ]
    if cita.convenio != Cita.CONVENIO_PRIVADO:
        filas.append(('Carné IGSS:', paciente.carnet_igss or 'No registrado'))
    filas += [
        ('Teléfono:', paciente.telefono or 'No registrado'),
        ('Convenio:', cita.get_convenio_display()),
        ('Fecha de cita:', cita.fecha.strftime('%d/%m/%Y')),
    ]
    return filas


@login_required
@user_passes_test(puede_ver_comprobante_pago)
def boleta_pago_pdf(request, cobro_id):
    """Recibo / boleta de pago imprimible de un cobro ya registrado como
    pagado, con formato de recibo (encabezado, datos del paciente, tabla de
    servicios y firma de conformidad). Para estudios del convenio Privado
    NO se muestra el carné del IGSS."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    cobro = get_object_or_404(
        sucursales.permitidas(Cobro.objects.select_related('cita__paciente', 'cita__tipo_estudio', 'cobrado_por'), request.user, 'cita__sucursal'),
        id=cobro_id, estado=Cobro.ESTADO_PAGADO,
    )
    cita = cobro.cita
    paciente = cita.paciente
    monto = cita.precio

    azul = colors.HexColor('#1d3a8a')
    gris = colors.HexColor('#cbd5e1')

    base = getSampleStyleSheet()['BodyText']
    base.fontSize = 9
    base.leading = 13
    negrita = {'parent': base, 'fontName': 'Helvetica-Bold'}
    st_clinica = ParagraphStyle('clinica', fontSize=16, textColor=azul, **negrita)
    st_recibo = ParagraphStyle('recibo', fontSize=13, alignment=TA_CENTER, **negrita)
    st_seccion = ParagraphStyle('seccion', fontSize=9, alignment=TA_CENTER, **negrita)
    st_derecha = ParagraphStyle('derecha', parent=base, alignment=TA_RIGHT)
    st_caja_lbl = ParagraphStyle('cajalbl', fontSize=8, **negrita)
    st_firma = ParagraphStyle('firma', parent=base, fontSize=8, alignment=TA_CENTER, leading=11)

    def caja(label, valor, ancho_lbl, ancho_val):
        t = Table([[Paragraph(label, st_caja_lbl), str(valor)]], colWidths=[ancho_lbl, ancho_val])
        t.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, azul),
            ('ROUNDEDCORNERS', [4, 4, 4, 4]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        return t

    fecha_pago = cobro.pagado_en.strftime('%d/%m/%Y') if cobro.pagado_en else ''
    encabezado = Table(
        [[
            Paragraph(CLINICA_NOMBRE, st_clinica),
            caja('FECHA:', fecha_pago, 1.5 * cm, 2.4 * cm),
            caja('EXPEDIENTE:', paciente.expediente or '—', 2.9 * cm, 2.0 * cm),
        ]],
        colWidths=[6.8 * cm, 4.2 * cm, 5.2 * cm],
    )
    encabezado.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))

    # Datos del paciente (sin carné IGSS si es un estudio privado).
    datos_paciente = [[etiqueta, valor] for etiqueta, valor in datos_paciente_boleta(cita)]
    tabla_paciente = Table(datos_paciente, colWidths=[3 * cm, 12 * cm])
    tabla_paciente.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
    ]))

    # Tabla de servicios (Cantidad / Descripción / Precio): el estudio
    # agendado más cualquier estudio extra que haya agregado el radiólogo
    # (ver EstudioExtra), cada uno en su propia fila.
    items_servicio = [(cita.tipo_estudio.nombre, cita.precio_base)]
    items_servicio += [
        (e.tipo_estudio.nombre, e.precio) for e in cita.estudios_extra_cobrados
    ]

    filas_servicio = [['Cantidad', 'Descripción', 'Precio']]
    filas_servicio += [['1', nombre, f'Q{precio:.2f}'] for nombre, precio in items_servicio]
    for _ in range(max(0, 2 - len(items_servicio))):
        filas_servicio.append(['', '', ''])
    filas_servicio.append(['', 'Total:', f'Q{monto:.2f}'])
    tabla_servicio = Table(filas_servicio, colWidths=[2.6 * cm, 11.4 * cm, 4.0 * cm])
    tabla_servicio.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), azul),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('ALIGN', (1, -1), (1, -1), 'RIGHT'),
        ('FONTNAME', (1, -1), (2, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, gris),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 1), (-1, -1), 8), ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))

    pago_detalle = Table(
        [
            ['Forma de pago:', cobro.get_forma_pago_display() or 'No registrada',
             'Referencia:', cobro.numero_boleta or 'No registrada'],
            ['Pagado el:', cobro.pagado_en.strftime('%d/%m/%Y %H:%M') if cobro.pagado_en else '',
             'Registró:', cobro.cobrado_por.get_full_name() or cobro.cobrado_por.username],
        ],
        colWidths=[3 * cm, 6 * cm, 2.5 * cm, 6.5 * cm],
    )
    pago_detalle.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))

    firma = Table(
        [[Paragraph('<br/><br/><br/>Firma de conformidad del paciente por el estudio realizado.', st_firma)]],
        colWidths=[7.5 * cm],
    )
    firma.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, azul),
        ('ROUNDEDCORNERS', [4, 4, 4, 4]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    elementos = [
        encabezado,
        Spacer(1, 16),
        Paragraph('RECIBO DE PAGO', st_recibo),
        Spacer(1, 4),
        Paragraph(f'N° de boleta: {cobro.id}', st_derecha),
        Spacer(1, 10),
        Paragraph(
            f'<b>{CLINICA_NOMBRE}</b><br/>{CLINICA_RUBRO}<br/>'
            f'Dirección: {CLINICA_DIRECCION}<br/>Tel: {CLINICA_TELEFONO}',
            base,
        ),
        Spacer(1, 16),
        Paragraph('DESCRIPCIÓN DE LOS SERVICIOS PRESTADOS AL PACIENTE', st_seccion),
        Spacer(1, 10),
        Paragraph(f'<b>Nombre del paciente:</b> {paciente.nombre} {paciente.apellido}', base),
        Spacer(1, 4),
        tabla_paciente,
        Spacer(1, 12),
        tabla_servicio,
        Spacer(1, 14),
        pago_detalle,
        Spacer(1, 40),
        firma,
    ]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm, title=f'Boleta de pago {cobro.id}',
    )
    doc.build(elementos)

    respuesta = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    respuesta['Content-Disposition'] = f'inline; filename="boleta_pago_{cobro.id}.pdf"'
    return respuesta


@login_required
@user_passes_test(puede_ver_comprobante_pago)
def comprobante_bancario(request, cobro_id):
    """Muestra en el navegador la boleta bancaria (depósito/transferencia) que
    Caja adjuntó al cobrar. Solo cobros pagados de las sucursales del usuario."""
    cobro = get_object_or_404(
        sucursales.permitidas(Cobro.objects.select_related('cita'), request.user, 'cita__sucursal'),
        id=cobro_id,
        estado=Cobro.ESTADO_PAGADO,
    )
    if not cobro.comprobante_bancario:
        raise Http404('Este pago no tiene una boleta bancaria cargada.')
    if not cobro.comprobante_bancario.storage.exists(cobro.comprobante_bancario.name):
        raise Http404('El archivo de la boleta bancaria ya no está disponible en el servidor.')
    return FileResponse(
        cobro.comprobante_bancario.open('rb'),
        as_attachment=False,
        filename=cobro.comprobante_bancario.name.rsplit('/', 1)[-1],
    )


@login_required
@user_passes_test(puede_ver_comprobante_pago)
def constancia_pago_pdf(request, cobro_id):
    """Genera la constancia interna, separada de la boleta bancaria."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    cobro = get_object_or_404(
        sucursales.permitidas(Cobro.objects.select_related('cita__paciente', 'cita__tipo_estudio', 'cobrado_por'), request.user, 'cita__sucursal'),
        id=cobro_id,
        estado=Cobro.ESTADO_PAGADO,
    )
    cita = cobro.cita
    paciente = cita.paciente
    estilos = getSampleStyleSheet()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        leftMargin=2 * cm, rightMargin=2 * cm,
        title=f'Constancia de pago {cobro.id}',
    )
    datos = [
        ['Paciente', f'{paciente.nombre} {paciente.apellido}'],
        ['DPI / expediente', f'{paciente.dpi} / {paciente.expediente or "—"}'],
        ['Estudio', cita.tipo_estudio.nombre],
        ['Convenio', cita.get_convenio_display()],
        ['Monto', f'Q{cita.precio:.2f}'],
        ['Forma de pago', cobro.get_forma_pago_display() or 'No registrada'],
        ['Boleta / referencia', cobro.numero_boleta or 'No registrada'],
        ['Fecha de registro', cobro.pagado_en.strftime('%d/%m/%Y %H:%M') if cobro.pagado_en else ''],
        ['Registrado por', cobro.cobrado_por.get_full_name() or cobro.cobrado_por.username],
    ]
    tabla = Table(datos, colWidths=[5 * cm, 11 * cm])
    tabla.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#eff6ff')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    firmas = Table([
        ['Recepcionista', 'Técnico', 'Radiólogo'],
        ['\n\n\nFirma y fecha', '\n\n\nFirma y fecha', '\n\n\nFirma y fecha'],
    ], colWidths=[5.3 * cm] * 3)
    firmas.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#64748b')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    doc.build([
        Paragraph('CONSTANCIA INTERNA DE PAGO RECIBIDO', estilos['Title']),
        Paragraph(
            'Esta constancia es un respaldo interno y no sustituye la boleta bancaria '
            'o comprobante de transferencia.',
            estilos['BodyText'],
        ),
        Spacer(1, 16),
        tabla,
        Spacer(1, 36),
        firmas,
    ])
    respuesta = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    respuesta['Content-Disposition'] = f'inline; filename="constancia_pago_{cobro.id}.pdf"'
    return respuesta


@login_required
@user_passes_test(puede_ver_comprobante_pago)
def constancia_firmada(request, cobro_id):
    """Muestra la constancia de pago firmada que se subió para un cobro pagado."""
    cobro = get_object_or_404(
        sucursales.permitidas(Cobro.objects.select_related('cita'), request.user, 'cita__sucursal'),
        id=cobro_id,
        estado=Cobro.ESTADO_PAGADO,
    )
    if not cobro.constancia_firmada:
        raise Http404('Este pago todavía no tiene una constancia firmada.')
    return FileResponse(
        cobro.constancia_firmada.open('rb'),
        as_attachment=False,
        filename=cobro.constancia_firmada.name.rsplit('/', 1)[-1],
    )


@login_required
@user_passes_test(puede_ver_comprobante_pago)
@require_POST
def subir_constancia_firmada(request, cobro_id):
    """Caja sube la constancia de pago firmada por el paciente (escaneada) y
    queda registrado quién y cuándo la subió."""
    cobro = get_object_or_404(sucursales.permitidas(Cobro.objects, request.user, 'cita__sucursal'), id=cobro_id, estado=Cobro.ESTADO_PAGADO)
    form = SubirConstanciaFirmadaForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'Seleccione una constancia firmada válida.')
        return redirect('pagos_pendientes')
    cobro.constancia_firmada = form.cleaned_data['constancia_firmada']
    cobro.constancia_subida_por = request.user
    cobro.constancia_subida_en = timezone.now()
    cobro.save(update_fields=['constancia_firmada', 'constancia_subida_por', 'constancia_subida_en'])
    messages.success(request, 'La constancia firmada se cargó correctamente.')
    return redirect('pagos_pendientes')


@login_required
@user_passes_test(es_caja)
@require_POST
def marcar_cobrado(request, cita_id):
    """Registra la boleta y marca el cobro como pagado."""
    cita = get_object_or_404(
        sucursales.permitidas(Cita.objects.filter(
            estado__in=(Cita.ESTADO_EN_PROCESO, Cita.ESTADO_PROCESADA),
            orden_trabajo__isnull=False,
        ), request.user),
        id=cita_id,
    )
    cobro, _creado = Cobro.objects.get_or_create(cita=cita)
    if not cobro.listo_para_cobrar:
        messages.error(
            request,
            'Todavía no se puede cobrar este estudio: el técnico debe confirmar primero que es el correcto.',
        )
        return redirect('pagos_pendientes')
    form = RegistrarPagoEstudioForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'Revisá los datos de la boleta antes de guardar.')
        return redirect('pagos_pendientes')

    if form.cleaned_data['forma_pago'] == Cobro.FORMA_EFECTIVO:
        try:
            monto_recibido = Decimal((request.POST.get('monto_recibido') or '').strip())
        except InvalidOperation:
            monto_recibido = None
        if monto_recibido is not None and not monto_recibido.is_finite():
            monto_recibido = None  # NaN / Infinity llegan como "válidos" a Decimal
        if monto_recibido is None or monto_recibido < cita.precio:
            messages.error(
                request,
                f'En efectivo la cantidad recibida debe cubrir el total del estudio '
                f'(Q{cita.precio:.2f}): no se puede marcar pagado si falta dinero.',
            )
            return redirect('pagos_pendientes')

    cobro.forma_pago = form.cleaned_data['forma_pago']
    cobro.numero_boleta = form.cleaned_data['numero_boleta']
    cobro.comprobante_bancario = form.cleaned_data['comprobante_bancario']
    cobro.marcar_pagado(request.user, notas=form.cleaned_data['notas'])
    cobro.save(update_fields=['forma_pago', 'numero_boleta', 'comprobante_bancario'])

    Bitacora.registrar(
        request=request,
        usuario=request.user,
        accion=Bitacora.ACCION_MARCAR_COBRADO,
        descripcion=f'Marcó como cobrado el estudio de {cita.paciente} (cita #{cita.id}).',
    )
    messages.success(request, f'Estudio de {cita.paciente} marcado como cobrado.')
    _intentar_envio_automatico(request, cita)
    return redirect('pagos_pendientes')
