"""Médicos tratantes (los que refieren pacientes) y el reporte/pago de su comisión.
"""
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Bitacora
from accounts.views import es_administrador

from ..forms import MedicoTratanteForm, PagoComisionMedicoTratanteForm
from ..models import MedicoTratante, PagoComisionMedicoTratante, PagoComisionMedicoTratanteLinea
from .comun import CLINICA_DIRECCION, CLINICA_NOMBRE, CLINICA_RUBRO, CLINICA_TELEFONO


@login_required
@user_passes_test(es_administrador)
def lista_medicos_tratantes(request):
    """Catálogo administrable de médicos tratantes (COEX / Emergencia
    IGSS): se elige uno de esta lista al agendar en vez de escribirlo a
    mano cada vez (ver AgendarCitaForm/ProcesarTicketForm)."""
    busqueda = (request.GET.get('q') or '').strip()

    medicos = MedicoTratante.objects.all().order_by('nombre')
    if busqueda:
        medicos = medicos.filter(nombre__icontains=busqueda)

    return render(request, 'pacientes/lista_medicos_tratantes.html', {
        'medicos': medicos,
        'busqueda': busqueda,
    })


@login_required
@user_passes_test(es_administrador)
def crear_medico_tratante(request):
    if request.method == 'POST':
        form = MedicoTratanteForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            medico = MedicoTratante.objects.create(
                nombre=cd['nombre'], dpi=cd['dpi'] or None, correo=cd['correo'], tipo=cd['tipo'],
                acceso_otp=cd['acceso_otp'], numero_colegiado=cd['numero_colegiado'] or None,
            )
            messages.success(request, f'Médico tratante "{medico.nombre}" creado correctamente.')
            return redirect('lista_medicos_tratantes')
    else:
        form = MedicoTratanteForm()

    return render(request, 'pacientes/crear_medico_tratante.html', {'form': form, 'editando': None})


@login_required
@user_passes_test(es_administrador)
def editar_medico_tratante(request, medico_id):
    medico = get_object_or_404(MedicoTratante, id=medico_id)

    if request.method == 'POST':
        form = MedicoTratanteForm(request.POST, medico_actual=medico)
        if form.is_valid():
            cd = form.cleaned_data
            medico.nombre = cd['nombre']
            medico.dpi = cd['dpi'] or None
            medico.correo = cd['correo']
            medico.tipo = cd['tipo']
            medico.acceso_otp = cd['acceso_otp']
            medico.numero_colegiado = cd['numero_colegiado'] or None
            medico.save(update_fields=[
                'nombre', 'dpi', 'correo', 'tipo', 'acceso_otp', 'numero_colegiado', 'actualizado_en',
            ])
            messages.success(request, f'Médico tratante "{medico.nombre}" actualizado correctamente.')
            return redirect('lista_medicos_tratantes')
    else:
        form = MedicoTratanteForm(initial={
            'nombre': medico.nombre, 'dpi': medico.dpi or '', 'correo': medico.correo, 'tipo': medico.tipo,
            'acceso_otp': medico.acceso_otp, 'numero_colegiado': medico.numero_colegiado or '',
        }, medico_actual=medico)

    return render(request, 'pacientes/crear_medico_tratante.html', {
        'form': form, 'editando': medico, 'medico': medico,
    })


@login_required
@user_passes_test(es_administrador)
@require_POST
def eliminar_medico_tratante(request, medico_id):
    medico = get_object_or_404(MedicoTratante, id=medico_id)
    medico.activo = False
    medico.save(update_fields=['activo', 'actualizado_en'])
    messages.success(request, f'Médico tratante "{medico.nombre}" desactivado correctamente.')
    return redirect('lista_medicos_tratantes')


@login_required
@user_passes_test(es_administrador)
@require_POST
def activar_medico_tratante(request, medico_id):
    medico = get_object_or_404(MedicoTratante, id=medico_id)
    medico.activo = True
    medico.save(update_fields=['activo', 'actualizado_en'])
    messages.success(request, f'Médico tratante "{medico.nombre}" activado correctamente.')
    return redirect('lista_medicos_tratantes')


def _periodo_comision_medico_tratante(request, medico):
    """Igual que accounts.periodos.resolver_periodo, pero por default (sin
    `modo` en el querystring) arranca en la cita pendiente de pago más
    antigua de `medico` y llega hasta hoy, en vez del mes actual -- así un
    reporte nuevo automáticamente sigue donde quedó pendiente el anterior.
    Devuelve (periodo, query) -- query ya es '' para el modo pendiente, no
    hace falta armar el querystring de resolver_periodo para ese caso."""
    from accounts.periodos import querystring, resolver_periodo

    from ..comisiones_medico_tratante import primera_fecha_pendiente

    if request.GET.get('modo'):
        periodo = resolver_periodo(request)
        return periodo, querystring(periodo)

    hoy = timezone.localdate()
    desde = primera_fecha_pendiente(medico) or hoy
    periodo = {
        'modo': 'pendiente', 'desde': desde, 'hasta': hoy,
        'etiqueta': f'Pendiente de pago (desde {desde:%d/%m/%Y})',
    }
    return periodo, ''


@login_required
@user_passes_test(es_administrador)
def reporte_comision_medico_tratante(request, medico_id):
    """Reporte de comisión por referencia de un médico tratante: cuántas
    citas Privado procesadas refirió en el período y cuánto suman, para que
    el administrador decida cuánto pagarle de comisión y lo registre (con
    comprobante). Sin elegir un período a mano arranca en la cita pendiente
    de pago más antigua y llega hasta hoy -- así un reporte de un mes
    arranca automáticamente donde quedó pendiente el anterior. También se
    puede elegir semana, quincena, mes o un rango libre (mismo selector que
    la Planilla de empleados, ver accounts.periodos)."""
    from ..comisiones_medico_tratante import (
        calcular_comision, citas_pendientes_de_pago, desglose_por_sucursal, parsear_porcentaje, resumen,
    )

    medico = get_object_or_404(MedicoTratante, id=medico_id)
    if medico.tipo == MedicoTratante.TIPO_IGSS:
        messages.error(
            request,
            f'{medico.nombre} está clasificado como IGSS: esta comisión es solo para referencias '
            'de Privado, así que nunca va a tener nada que reportar acá.',
        )
        return redirect('lista_medicos_tratantes')
    periodo, query = _periodo_comision_medico_tratante(request, medico)

    datos = resumen(citas_pendientes_de_pago(medico, periodo['desde'], periodo['hasta']))

    # El porcentaje no se guarda por médico: el administrador lo escribe en el reporte
    # (llega por la URL, igual que el período) y la comisión se calcula al instante.
    texto_porcentaje = (request.GET.get('porcentaje') or '').strip()
    porcentaje = parsear_porcentaje(texto_porcentaje)
    if texto_porcentaje and porcentaje is None:
        messages.error(request, 'El porcentaje debe ser un número mayor que 0 y hasta 100.')
    comision = calcular_comision(datos['total'], porcentaje) if porcentaje is not None else None

    if request.method == 'POST':
        form = PagoComisionMedicoTratanteForm(request.POST, request.FILES)
        if not datos['citas']:
            messages.error(request, 'No hay citas pendientes de pago en este período.')
        elif form.is_valid():
            cd = form.cleaned_data
            pago = PagoComisionMedicoTratante.objects.create(
                medico_tratante=medico, desde=periodo['desde'], hasta=periodo['hasta'],
                monto=cd['monto'], comprobante=cd['comprobante'],
                numero_boleta=cd['numero_boleta'], notas=cd['notas'],
                porcentaje=porcentaje, registrado_por=request.user,
            )
            PagoComisionMedicoTratanteLinea.objects.bulk_create([
                PagoComisionMedicoTratanteLinea(pago=pago, cita=cita, precio=cita.precio)
                for cita in datos['citas']
            ])
            Bitacora.registrar(
                request=request, usuario=request.user,
                accion=Bitacora.ACCION_PAGAR_COMISION_MEDICO_TRATANTE,
                descripcion=(
                    f'Pagó Q{pago.monto:.2f} de comisión a {medico.nombre} por '
                    f'{len(datos["citas"])} estudio(s) referido(s) ({pago.periodo_etiqueta}).'
                ),
            )
            messages.success(
                request,
                f'Pago de Q{pago.monto:.2f} registrado para {medico.nombre} '
                f'({len(datos["citas"])} estudio(s) referido(s)).',
            )
            destino = reverse('reporte_comision_medico_tratante', args=[medico.id])
            return redirect(f'{destino}?{query}' if query else destino)
    else:
        # Con porcentaje, el monto a pagar ya viene calculado (el administrador lo puede ajustar).
        form = PagoComisionMedicoTratanteForm(initial={'monto': comision} if comision else None)

    pagos_anteriores = (
        medico.pagos_comision.select_related('registrado_por').prefetch_related('lineas__cita__paciente')
    )

    return render(request, 'pacientes/reporte_comision_medico_tratante.html', {
        'medico': medico,
        'periodo': periodo,
        'query': query,
        'datos': datos,
        'porcentaje': porcentaje,
        'porcentaje_texto': f'{porcentaje:f}'.rstrip('0').rstrip('.') if porcentaje is not None else '',
        'comision': comision,
        'otros_parametros': [(k, v) for k, v in request.GET.items() if k != 'porcentaje'],
        'form': form,
        'pagos_anteriores': pagos_anteriores,
        'por_sucursal': desglose_por_sucursal(datos['citas']),
    })


@login_required
@user_passes_test(es_administrador)
def comision_medico_tratante_pdf(request, medico_id):
    """PDF imprimible con el detalle de las citas Privado pendientes de
    pago de un médico tratante en el período elegido (mismo período que
    reporte_comision_medico_tratante) -- una fila por estudio referido y el
    total general, para que el administrador decida cuánto pagarle."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from ..comisiones_medico_tratante import (
        calcular_comision, citas_pendientes_de_pago, parsear_porcentaje, resumen,
    )

    medico = get_object_or_404(MedicoTratante, id=medico_id)
    hoy = timezone.localdate()
    periodo, _query = _periodo_comision_medico_tratante(request, medico)

    datos = resumen(citas_pendientes_de_pago(medico, periodo['desde'], periodo['hasta']))

    azul = colors.HexColor('#1d3a8a')
    gris = colors.HexColor('#cbd5e1')

    base = getSampleStyleSheet()['BodyText']
    base.fontSize = 9
    base.leading = 13
    negrita = {'parent': base, 'fontName': 'Helvetica-Bold'}
    st_titulo = ParagraphStyle('titulo', fontSize=13, alignment=TA_CENTER, **negrita)
    st_derecha = ParagraphStyle('derecha', parent=base, alignment=TA_RIGHT)

    filas = [['Fecha', 'Paciente', 'Estudio', 'Precio']]
    for cita in datos['citas']:
        filas.append([
            cita.fecha.strftime('%d/%m/%Y'),
            f'{cita.paciente.nombre} {cita.paciente.apellido}',
            cita.tipo_estudio.nombre,
            f'Q{cita.precio:.2f}',
        ])
    filas.append(['', '', 'Total:', f'Q{datos["total"]:.2f}'])
    porcentaje = parsear_porcentaje(request.GET.get('porcentaje'))
    if porcentaje is not None:
        comision = calcular_comision(datos['total'], porcentaje)
        filas.append(['', '', f'Comisión ({porcentaje:f}%):'.replace('.00%', '%'), f'Q{comision:.2f}'])

    tabla = Table(filas, colWidths=[2.6 * cm, 5.5 * cm, 5.5 * cm, 3.0 * cm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), azul),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (2, -1), (3, -1), 'Helvetica-Bold'),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, gris),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
    ]))

    etiqueta_periodo = periodo.get('etiqueta') or f'Pendiente de pago desde {periodo["desde"]:%d/%m/%Y}'
    elementos = [
        Paragraph(
            f'<b>{CLINICA_NOMBRE}</b><br/>{CLINICA_RUBRO}<br/>'
            f'Dirección: {CLINICA_DIRECCION}<br/>Tel: {CLINICA_TELEFONO}',
            base,
        ),
        Spacer(1, 14),
        Paragraph('COMISIÓN POR REFERENCIA DE MÉDICO TRATANTE', st_titulo),
        Spacer(1, 4),
        Paragraph(f'Generado el {hoy:%d/%m/%Y}', st_derecha),
        Spacer(1, 10),
        Paragraph(
            f'<b>Médico tratante:</b> {medico.nombre}<br/>'
            f'<b>Período:</b> {etiqueta_periodo}<br/>'
            f'<b>Cantidad de estudios referidos:</b> {datos["cantidad"]}',
            base,
        ),
        Spacer(1, 14),
        tabla,
    ]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm, title=f'Comisión {medico.nombre}',
    )
    doc.build(elementos)

    respuesta = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    respuesta['Content-Disposition'] = f'inline; filename="comision_{medico.id}_{hoy:%Y%m%d}.pdf"'
    return respuesta
