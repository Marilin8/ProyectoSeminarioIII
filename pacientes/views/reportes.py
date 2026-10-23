"""Reportes diarios de radiología por convenio (pantalla, PDF y Excel) e informe anual.

Los totales usan el precio vigente en la fecha de cada estudio (historial de
precios), no el precio actual.
"""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts import sucursales
from accounts.models import MESES_ES, Bitacora, Usuario
from accounts.views import es_administrador

from ..models import Cita, MedicoTratante, Notificacion, ReporteDiario
from .permisos import (
    es_administrador_financiero,
    es_recepcionista,
    puede_descargar_reportes_diarios,
    puede_ver_comprobante_pago,
    puede_ver_reportes_diarios,
)


def _notificar_reporte_enviado(reporte, enviado_por):
    """Cuando la recepcionista envía el reporte diario, se avisa a todo el
    equipo de administración financiera para que puedan revisarlo."""
    destinatarios = sucursales.de_usuarios(Usuario.objects.filter(rol=Usuario.ROL_ADMINISTRADOR_FINANCIERO, is_active=True), reporte.sucursal)
    Notificacion.notificar_a_varios(
        usuarios=destinatarios,
        tipo=Notificacion.TIPO_REPORTE_ENVIADO,
        mensaje=(
            f'Nuevo reporte diario enviado: {reporte.get_convenio_display()} del {reporte.fecha}, '
            f'por {enviado_por.get_full_name() or enviado_por.username}.'
        ),
        url=reporte_url(reporte),
    )


# --- Reportes diarios ---------------------------------------------------
#
# Un ReporteDiario existe por (convenio, fecha). Se crea automáticamente en
# estado "borrador" la primera vez que un radiólogo confirma una cita de ese
# convenio para esa fecha (ver revisar_solicitud). Su contenido (las citas)
# no se guarda aparte: se calcula en el momento a partir de Cita, así nunca
# queda desactualizado. La recepcionista puede editar el médico referente de
# cada fila mientras el reporte esté en borrador, y enviarlo cuando termine
# el día; el administrador financiero solo ve los reportes ya enviados, y
# puede descargarlos en PDF o Excel.

DIAS_LARGOS_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MESES_LARGOS_ES = [
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]

COLUMNAS_REPORTE = [
    'No.', 'Hora', 'Nombre del Paciente', 'Edad', 'Estudio',
    'Técnico', 'Médico Referente', 'Emerg', 'Radiólogo', 'Precio',
]

# Solo el reporte de Privado lleva estas columnas extra (placas y estado del pago).
CAMPOS_PLACAS = ('placas_10x12', 'placas_14x17', 'placas_error_10x12', 'placas_error_14x17')
COLUMNAS_REPORTE_PRIVADO = [
    'Placas 10×12', 'Placas 14×17', 'Error 10×12', 'Error 14×17', 'Cancelado', 'Forma de pago',
]
PLACAS_MAXIMO_POR_ESTUDIO = 99


def _cantidad_de_placas(texto):
    """Cantidad escrita en un campo de placas: vacío cuenta como 0; solo enteros de 0 a 99.
    Devuelve None si no es válida."""
    texto = (texto or '').strip()
    if not texto:
        return 0
    if not (texto.isascii() and texto.isdigit()):
        return None
    cantidad = int(texto)
    return cantidad if cantidad <= PLACAS_MAXIMO_POR_ESTUDIO else None


def _totales_placas(filas):
    return {campo: sum(fila.get(campo) or 0 for fila in filas) for campo in CAMPOS_PLACAS}


def _fecha_larga_es(fecha):
    dia_semana = DIAS_LARGOS_ES[fecha.weekday()]
    mes = MESES_LARGOS_ES[fecha.month - 1]
    return f'{dia_semana} {fecha.day} de {mes} de {fecha.year}'


def _validar_convenio(convenio):
    if convenio not in dict(Cita.CONVENIO_CHOICES):
        raise Http404('Convenio no válido.')


def _solo_ve_reportes_enviados(user):
    """True si debe ver los reportes en modo solo-lectura (solo los ya
    enviados): administrador financiero o administrador general, distinto
    de una recepcionista que también tenga alguno de esos roles de prueba
    (superusuario) — a esa se le sigue tratando como recepcionista."""
    return (
        (es_administrador_financiero(user) or es_administrador(user))
        and not es_recepcionista(user)
    )


def _filas_reporte(reporte):
    filas = []
    es_privado = reporte.convenio == Cita.CONVENIO_PRIVADO
    for indice, cita in enumerate(reporte.citas(), start=1):
        tecnicos = _tecnicos_que_atendieron(cita)
        fila = {
            'no': indice,
            'cita_id': cita.id,
            'hora': cita.hora.strftime('%H:%M'),
            'paciente': f'{cita.paciente.nombre} {cita.paciente.apellido}',
            'edad': cita.paciente.edad_en(cita.fecha),
            'estudio': cita.tipo_estudio.nombre,
            # Técnico(s) que subieron las imágenes del estudio: si hay varios técnicos
            # en turno, así se sabe quién lo atendió.
            'tecnico': ', '.join(tecnicos),
            'tecnico_pendiente': not tecnicos and cita.estado != Cita.ESTADO_AUSENTE,
            # El médico referente es el médico tratante de la cita; el texto libre
            # de antes (medico_referente) solo se muestra si no tiene uno elegido.
            'medico_referente': cita.medico_tratante.nombre if cita.medico_tratante_id else cita.medico_referente,
            'medico_tratante_id': cita.medico_tratante_id,
            'emerg': 'X' if cita.convenio == Cita.CONVENIO_EMERGENCIA_IGSS else '',
            'radiologo': (
                (cita.radiologo.get_full_name() or cita.radiologo.username) if cita.radiologo else ''
            ),
            'precio': cita.precio,
            'ausente': cita.estado == Cita.ESTADO_AUSENTE,
        }
        if es_privado:
            cobro = getattr(cita, 'cobro', None)
            pagado = bool(cobro and cobro.pagado) and not fila['ausente']
            fila.update({campo: getattr(cita, campo) for campo in CAMPOS_PLACAS})
            fila.update({
                'cancelado': pagado,
                'forma_pago': (cobro.get_forma_pago_display() or 'No registrada') if pagado else '',
                'cobro_id': cobro.id if pagado else None,
            })
        filas.append(fila)
    return filas


def _tecnicos_que_atendieron(cita):
    """Nombres de los técnicos que subieron imágenes del estudio, en el orden en que
    lo hicieron (sin repetir). Vacío si todavía no tiene imágenes."""
    orden = getattr(cita, 'orden_trabajo', None)
    if orden is None:
        return []
    nombres = []
    for imagen in orden.imagenes.select_related('subida_por').order_by('subida_en'):
        usuario = imagen.subida_por
        nombre = (usuario.get_full_name() or usuario.username) if usuario else ''
        if nombre and nombre not in nombres:
            nombres.append(nombre)
    return nombres


def _medicos_tratantes_para_reporte(reporte, filas):
    """Médicos para elegir en la columna "Médico referente": los del lado del convenio
    (Privado o IGSS) más los que ya tengan las citas del reporte."""
    lado = MedicoTratante.TIPO_PRIVADO if reporte.convenio == Cita.CONVENIO_PRIVADO else MedicoTratante.TIPO_IGSS
    ya_elegidos = {f['medico_tratante_id'] for f in filas if f['medico_tratante_id']}
    return MedicoTratante.objects.filter(
        Q(id__in=MedicoTratante.disponibles_para(lado).values('id')) | Q(id__in=ya_elegidos),
    ).order_by('nombre')


def _pacientes_con_datos_pendientes(reporte):
    """Pacientes del reporte (sexo/teléfono/fecha de nacimiento) que
    todavía tienen algún dato pendiente de llenar. Mientras existan, el
    reporte no se puede enviar al administrador."""
    pendientes = {}
    for cita in reporte.citas():
        paciente = cita.paciente
        if paciente.id in pendientes:
            continue
        campos = paciente.campos_pendientes()
        if campos:
            pendientes[paciente.id] = {
                'nombre': f'{paciente.nombre} {paciente.apellido}',
                'campos': campos,
            }
    return sorted(pendientes.values(), key=lambda p: p['nombre'])


def _reporte_pdf_bytes(reporte, filas):
    from io import BytesIO
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    privado = reporte.convenio == Cita.CONVENIO_PRIVADO
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(letter),
        topMargin=1 * cm, bottomMargin=1 * cm, leftMargin=1 * cm, rightMargin=1 * cm,
    )
    estilos = getSampleStyleSheet()
    titulo = Paragraph(
        f'INFORME DIARIO "{reporte.get_convenio_display().upper()}"<br/>'
        f'FECHA: {_fecha_larga_es(reporte.fecha).upper()}',
        estilos['Title'],
    )
    estilo_celda = ParagraphStyle('celda', parent=estilos['BodyText'], fontSize=7, leading=8)

    def texto(valor):
        # Con tantas columnas (Privado) los textos largos tienen que partirse en líneas.
        return Paragraph(escape(str(valor)), estilo_celda) if privado else valor

    encabezados = COLUMNAS_REPORTE + (COLUMNAS_REPORTE_PRIVADO if privado else [])
    datos = [encabezados]
    for fila in filas:
        celdas = [
            fila['no'], fila['hora'], texto(fila['paciente']),
            fila['edad'] if fila['edad'] is not None else '',
            texto(fila['estudio']), texto(fila['tecnico']), texto(fila['medico_referente']),
            fila['emerg'], texto(fila['radiologo']), f"Q{fila['precio']:.2f}",
        ]
        if privado:
            celdas += [fila[campo] or '' for campo in CAMPOS_PLACAS]
            celdas += ['Sí' if fila['cancelado'] else 'No', texto(fila['forma_pago'])]
        datos.append(celdas)
    fila_total = ['', '', '', '', '', '', '', '', 'TOTAL DEL DÍA', f'Q{reporte.total():.2f}']
    if privado:
        totales = _totales_placas(filas)
        fila_total += [totales[campo] for campo in CAMPOS_PLACAS] + ['', '']
    datos.append(fila_total)

    anchos = None
    if privado:
        anchos = [0.8, 1.0, 3.6, 0.9, 3.2, 2.2, 2.2, 0.9, 2.0, 1.6, 1.1, 1.1, 1.1, 1.1, 1.3, 1.8]
        anchos = [ancho * cm for ancho in anchos]
    tabla = Table(datos, repeatRows=1, colWidths=anchos)
    ultima_fila = len(datos) - 1
    estilo = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c4b5fd')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 7 if privado else 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('SPAN', (0, ultima_fila), (7, ultima_fila)),
        ('BACKGROUND', (8, ultima_fila), (9, ultima_fila), colors.HexColor('#fef08a')),
        ('FONTNAME', (8, ultima_fila), (9, ultima_fila), 'Helvetica-Bold'),
    ]
    if privado:
        estilo += [
            ('BACKGROUND', (10, 0), (13, 0), colors.HexColor('#a78bfa')),
            ('ALIGN', (10, 1), (14, -1), 'CENTER'),
            ('BACKGROUND', (10, ultima_fila), (13, ultima_fila), colors.HexColor('#fef08a')),
            ('FONTNAME', (10, ultima_fila), (13, ultima_fila), 'Helvetica-Bold'),
        ]
    tabla.setStyle(TableStyle(estilo))
    doc.build([titulo, Spacer(1, 12), tabla])
    return buffer.getvalue()


def _reporte_xlsx_bytes(reporte, filas):
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    privado = reporte.convenio == Cita.CONVENIO_PRIVADO
    columnas = COLUMNAS_REPORTE + (COLUMNAS_REPORTE_PRIVADO if privado else [])
    ultima_letra = get_column_letter(len(columnas))

    wb = Workbook()
    ws = wb.active
    ws.title = 'Reporte'

    ws.merge_cells(f'A1:{ultima_letra}1')
    ws['A1'] = f'INFORME DIARIO "{reporte.get_convenio_display().upper()}"'
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = Alignment(horizontal='center')

    ws.merge_cells(f'A2:{ultima_letra}2')
    ws['A2'] = f'FECHA: {_fecha_larga_es(reporte.fecha).upper()}'
    ws['A2'].alignment = Alignment(horizontal='center')

    ws.append([])
    ws.append(columnas)
    for celda in ws[ws.max_row]:
        celda.font = Font(bold=True, color='FFFFFF')
        celda.fill = PatternFill('solid', fgColor='7C3AED')

    for fila in filas:
        valores = [
            fila['no'], fila['hora'], fila['paciente'], fila['edad'], fila['estudio'],
            fila['tecnico'], fila['medico_referente'], fila['emerg'], fila['radiologo'],
            float(fila['precio']),
        ]
        if privado:
            valores += [fila[campo] or None for campo in CAMPOS_PLACAS]
            valores += ['Sí' if fila['cancelado'] else 'No', fila['forma_pago']]
        ws.append(valores)

    fila_total = ws.max_row + 1
    ws.cell(row=fila_total, column=9, value='TOTAL DEL DÍA').font = Font(bold=True)
    celda_total = ws.cell(row=fila_total, column=10, value=float(reporte.total()))
    celda_total.font = Font(bold=True)
    celda_total.fill = PatternFill('solid', fgColor='FEF08A')
    if privado:
        totales = _totales_placas(filas)
        for desplazamiento, campo in enumerate(CAMPOS_PLACAS):
            celda = ws.cell(row=fila_total, column=11 + desplazamiento, value=totales[campo])
            celda.font = Font(bold=True)
            celda.fill = PatternFill('solid', fgColor='FEF08A')

    encabezados_fila = 4
    for indice_columna in range(1, len(columnas) + 1):
        letra = get_column_letter(indice_columna)
        longitud = max(
            (
                len(str(ws.cell(row=fila, column=indice_columna).value))
                for fila in range(encabezados_fila, ws.max_row + 1)
                if ws.cell(row=fila, column=indice_columna).value is not None
            ),
            default=10,
        )
        ws.column_dimensions[letra].width = longitud + 2

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


@login_required
@user_passes_test(puede_ver_reportes_diarios)
def informe_anual(request):
    """Resumen anual de facturación por mes y convenio. Usa Cita.precio
    (que ya respeta el precio vigente en la fecha de cada cita, ver
    HistorialPrecioEstudio) -- si un estudio cambió de precio durante el
    año, esto lo refleja correctamente en vez de recalcular todo con la
    tarifa actual."""
    hoy = timezone.localdate()
    try:
        anio = int(request.GET.get('anio', hoy.year))
    except (TypeError, ValueError):
        anio = hoy.year

    citas = (
        sucursales.filtrar(Cita.objects.filter(fecha__year=anio), request)
        .exclude(estado__in=(Cita.ESTADO_PENDIENTE, Cita.ESTADO_RECHAZADA))
        .select_related('tipo_estudio')
        .prefetch_related(
            'tipo_estudio__precios', 'tipo_estudio__historial_precios',
            'estudios_extra__tipo_estudio__precios', 'estudios_extra__tipo_estudio__historial_precios',
        )
    )

    convenios = [c for c, _ in Cita.CONVENIO_CHOICES]
    por_mes = {mes: {c: Decimal('0.00') for c in convenios} for mes in range(1, 13)}
    cantidad_por_mes = {mes: 0 for mes in range(1, 13)}

    for cita in citas:
        if not cita.cuenta_en_total_reporte:
            continue
        por_mes[cita.fecha.month][cita.convenio] += cita.precio
        cantidad_por_mes[cita.fecha.month] += 1

    filas = [
        {
            'mes': mes,
            'nombre_mes': MESES_ES[mes],
            # Lista en el mismo orden que `convenios`, para poder recorrerla
            # en el template en paralelo con las columnas del encabezado
            # (Django no permite indexar un dict con una variable de loop).
            'valores_lista': [por_mes[mes][c] for c in convenios],
            'total': sum(por_mes[mes].values(), Decimal('0.00')),
            'cantidad': cantidad_por_mes[mes],
        }
        for mes in range(1, 13)
    ]
    totales_convenio = {
        c: sum((por_mes[mes][c] for mes in range(1, 13)), Decimal('0.00')) for c in convenios
    }
    totales_convenio_lista = [totales_convenio[c] for c in convenios]
    total_anual = sum(totales_convenio.values(), Decimal('0.00'))
    cantidad_anual = sum(cantidad_por_mes.values())
    promedio_por_cita = (total_anual / cantidad_anual) if cantidad_anual else Decimal('0.00')

    primer_anio_con_citas = (
        sucursales.filtrar(Cita.objects, request).exclude(estado__in=(Cita.ESTADO_PENDIENTE, Cita.ESTADO_RECHAZADA))
        .order_by('fecha').values_list('fecha', flat=True).first()
    )
    anio_mas_viejo = primer_anio_con_citas.year if primer_anio_con_citas else hoy.year
    anios_disponibles = list(range(hoy.year, anio_mas_viejo - 1, -1))
    if anio not in anios_disponibles:
        anios_disponibles.append(anio)
        anios_disponibles.sort(reverse=True)

    return render(request, 'pacientes/informe_anual.html', {
        'anio': anio,
        'anios_disponibles': anios_disponibles,
        'convenios': Cita.CONVENIO_CHOICES,
        'filas': filas,
        'totales_convenio_lista': totales_convenio_lista,
        'total_anual': total_anual,
        'cantidad_anual': cantidad_anual,
        'promedio_por_cita': promedio_por_cita,
        'sucursal': sucursales.sucursal_activa(request),
    })


@login_required
@user_passes_test(puede_ver_reportes_diarios)
def lista_reportes_diarios(request, convenio):
    convenio_nombre = dict(Cita.CONVENIO_CHOICES).get(convenio, convenio)
    solo_enviados = _solo_ve_reportes_enviados(request.user)

    # Red de seguridad: normalmente el reporte de una fecha se crea en el
    # momento en que se confirma o reagenda una cita para ella, pero por si
    # falta alguno (p. ej. citas ya confirmadas antes de tener esta lógica),
    # se completa aquí cualquier fecha con citas confirmadas que todavía no
    # tenga su ReporteDiario.
    fechas_con_citas = (
        Cita.objects.filter(convenio=convenio)
        .exclude(estado__in=(Cita.ESTADO_PENDIENTE, Cita.ESTADO_RECHAZADA))
        .order_by()
        .values_list('fecha', 'sucursal_id')
        .distinct()
    )
    fechas_existentes = set(
        ReporteDiario.objects.filter(convenio=convenio).values_list('fecha', 'sucursal_id')
    )
    for fecha, sucursal_id in fechas_con_citas:
        if (fecha, sucursal_id) not in fechas_existentes:
            ReporteDiario.objects.get_or_create(fecha=fecha, convenio=convenio, sucursal_id=sucursal_id)
    # El reporte de hoy existe desde las 00:00 (lo crea el programador cada
    # minuto); por si el servidor recién arrancó, también se asegura aquí.
    hoy = timezone.localdate()
    ReporteDiario.asegurar_del_dia(hoy)

    # Los reportes ya creados son el registro permanente: una vez que
    # existen, deben seguir apareciendo aunque las citas que los originaron
    # cambien después (se reagenden a otra fecha, se rechacen, etc.). Por
    # eso se listan desde ReporteDiario y no recalculando a partir de Cita
    # en cada visita. Se muestran hasta el día de hoy: el de hoy aparece
    # "en curso" y se va llenando con las citas que se confirman, pero no se
    # puede enviar hasta que el día termine (ver enviar_reporte_diario),
    # porque todavía puede haber citas que se cancelen, reagenden o
    # completen. Los de fechas futuras no se listan.
    reportes = sucursales.filtrar(ReporteDiario.objects.filter(
        convenio=convenio, fecha__lte=hoy,
    ), request).select_related('sucursal').order_by('-fecha', 'sucursal__nombre')
    if solo_enviados:
        reportes = reportes.filter(estado=ReporteDiario.ESTADO_ENVIADO)

    return render(request, 'pacientes/lista_reportes_diarios.html', {
        'convenio': convenio,
        'convenio_nombre': convenio_nombre,
        'reportes': reportes,
        'solo_enviados': solo_enviados,
    })


def reporte_url(reporte, nombre='ver_reporte_diario'):
    """URL de un reporte diario: la sucursal va en ?sucursal= porque hay un reporte
    por fecha, convenio y sucursal."""
    url = reverse(nombre, args=[reporte.convenio, reporte.fecha.strftime('%Y-%m-%d')])
    return f'{url}?sucursal={reporte.sucursal_id}' if reporte.sucursal_id else url


def _sucursal_del_reporte(request):
    """?sucursal= (si es una sucursal del usuario), si no la activa, si no la principal."""
    from accounts.models import Sucursal
    valor = request.GET.get('sucursal') or request.POST.get('sucursal')
    if valor and valor.isdigit():
        opciones = Sucursal.objects.all() if sucursales.ve_todas(request.user) else request.user.sucursales.all()
        elegida = opciones.filter(id=int(valor)).first()
        if elegida:
            return elegida
    return sucursales.sucursal_activa(request) or Sucursal.objects.filter(es_principal=True).first()


def _reporte_pedido(request, convenio, fecha_valor, **filtros):
    return get_object_or_404(
        ReporteDiario, convenio=convenio, fecha=fecha_valor, sucursal=_sucursal_del_reporte(request), **filtros,
    )


@login_required
@user_passes_test(puede_ver_reportes_diarios)
def ver_reporte_diario(request, convenio, fecha):
    _validar_convenio(convenio)
    fecha_valor = parse_date(fecha)
    if not fecha_valor:
        raise Http404('Fecha no válida.')

    reporte = _reporte_pedido(request, convenio, fecha_valor)
    solo_lectura = _solo_ve_reportes_enviados(request.user)
    if solo_lectura and reporte.estado != ReporteDiario.ESTADO_ENVIADO:
        raise Http404('Este reporte todavía no fue enviado.')

    editable = not solo_lectura and reporte.estado == ReporteDiario.ESTADO_BORRADOR

    if request.method == 'POST':
        if not editable:
            messages.error(request, 'Este reporte ya no se puede editar.')
            return redirect(request.path)
        con_placas_invalidas = []
        validos = {m.id: m for m in _medicos_tratantes_para_reporte(reporte, _filas_reporte(reporte))}
        for cita in reporte.citas():
            valor = request.POST.get(f'medico_tratante_{cita.id}')
            if valor is not None:
                medico = validos.get(int(valor)) if valor.isdigit() else None
                if (medico.id if medico else None) != cita.medico_tratante_id:
                    cita.medico_tratante = medico
                    cita.save(update_fields=['medico_tratante'])
            if reporte.convenio == Cita.CONVENIO_PRIVADO:
                cambios = []
                for campo in CAMPOS_PLACAS:
                    texto = request.POST.get(f'{campo}_{cita.id}')
                    if texto is None:
                        continue  # esa fila no trajo el campo (ej. cita ausente)
                    cantidad = _cantidad_de_placas(texto)
                    if cantidad is None:
                        if cita.paciente.nombre not in con_placas_invalidas:
                            con_placas_invalidas.append(cita.paciente.nombre)
                        continue
                    if cantidad != getattr(cita, campo):
                        setattr(cita, campo, cantidad)
                        cambios.append(campo)
                if cambios:
                    cita.save(update_fields=cambios)
        if con_placas_invalidas:
            messages.error(
                request,
                'Placas no válidas (use números enteros de 0 a 99) en: '
                + ', '.join(con_placas_invalidas) + '. Esas cantidades no se guardaron.',
            )
        messages.success(request, 'Cambios guardados.')
        return redirect(request.path)

    pacientes_pendientes = _pacientes_con_datos_pendientes(reporte)
    filas = _filas_reporte(reporte)
    medicos_tratantes = _medicos_tratantes_para_reporte(reporte, filas) if editable else []
    es_privado = convenio == Cita.CONVENIO_PRIVADO
    return render(request, 'pacientes/reporte_diario.html', {
        'reporte': reporte,
        'convenio_nombre': dict(Cita.CONVENIO_CHOICES).get(convenio, convenio),
        'columnas': COLUMNAS_REPORTE,
        'filas': filas,
        'es_privado': es_privado,
        'totales_placas': _totales_placas(filas) if es_privado else None,
        'puede_ver_recibo': puede_ver_comprobante_pago(request.user),
        'total': reporte.total(),
        'editable': editable,
        'solo_lectura': solo_lectura,
        'lista_url_name': f'lista_reportes_diarios_{convenio}',
        'pacientes_pendientes': pacientes_pendientes,
        'medicos_tratantes': medicos_tratantes,
        'en_curso': reporte.en_curso,
        'firma': reporte.firma() if reporte.en_curso else '',
        'segundos_actualizacion': SEGUNDOS_ACTUALIZACION_REPORTE,
    })


# Cada cuánto la página del reporte de hoy consulta si cambió.
SEGUNDOS_ACTUALIZACION_REPORTE = 20


@login_required
@user_passes_test(puede_ver_reportes_diarios)
def firma_reporte_diario(request, convenio, fecha):
    """Huella del contenido del reporte (ver ReporteDiario.firma): la
    página del reporte del día la consulta para recargarse sola cuando se
    agregan o cambian citas."""
    _validar_convenio(convenio)
    fecha_valor = parse_date(fecha)
    if not fecha_valor:
        raise Http404('Fecha no válida.')
    reporte = _reporte_pedido(request, convenio, fecha_valor)
    if _solo_ve_reportes_enviados(request.user) and reporte.estado != ReporteDiario.ESTADO_ENVIADO:
        raise Http404('Este reporte todavía no fue enviado.')
    return JsonResponse({'firma': reporte.firma(), 'citas': reporte.citas().count()})


@login_required
@user_passes_test(es_recepcionista)
def enviar_reporte_diario(request, convenio, fecha):
    _validar_convenio(convenio)
    fecha_valor = parse_date(fecha)
    if not fecha_valor:
        raise Http404('Fecha no válida.')

    reporte = _reporte_pedido(request, convenio, fecha_valor)
    volver_url = reporte_url(reporte)

    if request.method == 'POST' and reporte.estado == ReporteDiario.ESTADO_BORRADOR:
        if fecha_valor >= timezone.localdate():
            messages.error(
                request,
                'No se puede enviar el reporte de hoy ni de una fecha futura: todavía puede '
                'haber citas de ese día que se cancelen, reagenden o finalicen. Esperá a que '
                'el día termine.',
            )
            return redirect(volver_url)
        pendientes = _pacientes_con_datos_pendientes(reporte)
        if pendientes:
            nombres = ', '.join(paciente['nombre'] for paciente in pendientes)
            messages.error(
                request,
                'No se puede enviar el reporte: hay pacientes con datos pendientes de llenar '
                f'(sexo, teléfono o fecha de nacimiento): {nombres}.',
            )
            return redirect(volver_url)

        reporte.estado = ReporteDiario.ESTADO_ENVIADO
        reporte.enviado_por = request.user
        reporte.enviado_en = timezone.now()
        reporte.save(update_fields=['estado', 'enviado_por', 'enviado_en'])
        Bitacora.registrar(
            request=request,
            usuario=request.user,
            accion=Bitacora.ACCION_ENVIAR_REPORTE_DIARIO,
            descripcion=(
                f'Envió el reporte diario de {dict(Cita.CONVENIO_CHOICES).get(convenio, convenio)} '
                f'del {fecha_valor} al administrador.'
            ),
        )
        _notificar_reporte_enviado(reporte, request.user)
        messages.success(request, f'Reporte del {fecha_valor} enviado al administrador.')
    return redirect(volver_url)


@login_required
@user_passes_test(puede_descargar_reportes_diarios)
def descargar_reporte_pdf(request, convenio, fecha):
    _validar_convenio(convenio)
    fecha_valor = parse_date(fecha)
    if not fecha_valor:
        raise Http404('Fecha no válida.')
    reporte = _reporte_pedido(request, convenio, fecha_valor, estado=ReporteDiario.ESTADO_ENVIADO)
    contenido = _reporte_pdf_bytes(reporte, _filas_reporte(reporte))
    respuesta = HttpResponse(contenido, content_type='application/pdf')
    respuesta['Content-Disposition'] = f'attachment; filename="reporte_{convenio}_{fecha_valor}.pdf"'
    return respuesta


@login_required
@user_passes_test(puede_descargar_reportes_diarios)
def descargar_reporte_xlsx(request, convenio, fecha):
    _validar_convenio(convenio)
    fecha_valor = parse_date(fecha)
    if not fecha_valor:
        raise Http404('Fecha no válida.')
    reporte = _reporte_pedido(request, convenio, fecha_valor, estado=ReporteDiario.ESTADO_ENVIADO)
    contenido = _reporte_xlsx_bytes(reporte, _filas_reporte(reporte))
    respuesta = HttpResponse(
        contenido, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    respuesta['Content-Disposition'] = f'attachment; filename="reporte_{convenio}_{fecha_valor}.xlsx"'
    return respuesta
