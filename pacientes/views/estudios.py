"""Flujo técnico/radiólogo: órdenes pendientes, verificación del estudio,
carga de imágenes (JPG/DICOM), correcciones pedidas a recepción, informe del
radiólogo y estudios extra.
"""
import hashlib
import os
import time
import zipfile
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.base import ContentFile
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from accounts import sucursales
from accounts.models import Bitacora, Usuario

from ..dicom_utils import dicom_a_jpg_memoria
from ..forms import (
    AdjuntarImagenesForm,
    AdjuntarInformeForm,
    AgregarEstudioExtraForm,
    CorregirEstudioForm,
    EXTENSIONES_IMAGEN_DIRECTA,
    NOMBRES_IGNORADOS_EN_CARPETA,
    SolicitarModificacionEstudioForm,
)
from ..models import (
    Cita,
    Cobro,
    EstudioExtra,
    ImagenEstudio,
    InformeEstudio,
    Notificacion,
    OrdenTrabajo,
    TipoEstudio,
)
from .avisos import (
    _notificar_estudio_actualizado,
    _notificar_estudio_completado,
    _notificar_estudio_listo_para_informar,
    _notificar_estudio_validado,
    _notificar_modificacion_solicitada,
    _notificar_orden_pendiente,
)
from .citas import _hay_estudio_duplicado
from .envio_resultados import _intentar_envio_automatico, _intentar_envio_medico_tratante
from .permisos import es_radiologo, es_recepcionista, es_tecnico


MENSAJE_VERIFICAR_ESTUDIO = (
    'Antes de cargar las imágenes, confirmá si el estudio es el correcto o pedile '
    'a recepción que lo modifique.'
)


@login_required
@user_passes_test(es_tecnico)
def ordenes_pendientes(request):
    """Órdenes esperando que el técnico cargue las imágenes, con búsqueda
    por nombre/apellido/DPI y filtros por convenio, fecha de la cita y
    tipo de estudio (mismo patrón que historial_pacientes)."""
    busqueda = (request.GET.get('q') or '').strip()
    filtro_convenio = (request.GET.get('convenio') or '').strip()
    filtro_fecha = (request.GET.get('fecha') or '').strip()
    filtro_tipo_estudio = (request.GET.get('tipo_estudio') or '').strip()

    # "Pendiente" ahora depende de si YA hay imagen para cada estudio de la
    # cita (uno solo si no es combo, ver Cita.estudios) -- no es una columna,
    # así que se calcula en Python sobre los candidatos y se vuelve a
    # consultar por id para poder seguir filtrando/paginando a nivel SQL.
    candidatas = (
        sucursales.filtrar(OrdenTrabajo.objects.filter(cita__estado=Cita.ESTADO_EN_PROCESO), request, 'cita__sucursal')
        .select_related('cita', 'cita__tipo_estudio')
        .prefetch_related('imagenes', 'cita__tipo_estudio__combo_origen__estudios', 'cita__estudios_extra__tipo_estudio')
    )
    ids_pendientes = [o.id for o in candidatas if not o.imagenes_completas]

    ordenes = (
        OrdenTrabajo.objects.filter(id__in=ids_pendientes)
        .select_related('cita', 'cita__paciente', 'cita__tipo_estudio')
        .distinct()
    )
    if busqueda:
        ordenes = ordenes.filter(
            Q(cita__paciente__nombre__icontains=busqueda)
            | Q(cita__paciente__apellido__icontains=busqueda)
            | Q(cita__paciente__dpi__icontains=busqueda)
        )
    if filtro_convenio:
        ordenes = ordenes.filter(cita__convenio=filtro_convenio)
    if filtro_fecha:
        ordenes = ordenes.filter(cita__fecha=filtro_fecha)
    if filtro_tipo_estudio:
        ordenes = ordenes.filter(cita__tipo_estudio_id=filtro_tipo_estudio)

    ordenes = ordenes.order_by('creada_en')

    contexto = {
        'ordenes': ordenes,
        'busqueda': busqueda,
        'filtro_convenio': filtro_convenio,
        'filtro_fecha': filtro_fecha,
        'filtro_tipo_estudio': filtro_tipo_estudio,
        'tipos_estudio': TipoEstudio.objects.filter(
            id__in=OrdenTrabajo.objects.filter(id__in=ids_pendientes).values('cita__tipo_estudio_id')
        ).order_by('nombre'),
    }

    # Búsqueda en vivo: el JS de la página pide solo el listado (sin el
    # HTML completo) a medida que se escribe/filtra, igual que en
    # historial_pacientes.
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'pacientes/includes/_resultados_ordenes.html', contexto)

    return render(request, 'pacientes/ordenes_pendientes.html', contexto)


def _guardar_imagen_o_convertir_dicom(archivo, orden, usuario, tipo_estudio):
    """Guarda un archivo como ImagenEstudio (ligada a `tipo_estudio`, el
    estudio de la cita al que pertenece -- ver Cita.estudios): si ya es
    JPG/PNG lo guarda tal cual, si no (.dcm o sin extensión, como viene de
    la carpeta que exporta el equipo) intenta convertirlo de DICOM a JPG y
    conserva además el archivo DICOM original (para que la radióloga lo
    pueda descargar). Devuelve True si quedó guardada, False si se omitió
    (no era un DICOM válido).

    Guarda también la huella SHA-256 de los bytes recibidos (ver
    ImagenEstudio.huella_sha256 y views/agente.py)."""
    if archivo.name.lower().endswith(EXTENSIONES_IMAGEN_DIRECTA):
        huella = hashlib.sha256()
        archivo.seek(0)
        for bloque in archivo.chunks():
            huella.update(bloque)
        archivo.seek(0)
        ImagenEstudio.objects.create(
            orden=orden, tipo_estudio=tipo_estudio, archivo=archivo, subida_por=usuario,
            huella_sha256=huella.hexdigest(),
        )
        return True

    # dicom_a_jpg_memoria consume el stream del archivo al leerlo con
    # pydicom, así que hay que guardar los bytes originales antes.
    archivo.seek(0)
    contenido_original = archivo.read()
    archivo.seek(0)

    jpg_convertido = dicom_a_jpg_memoria(archivo)
    if jpg_convertido:
        nueva_imagen = ImagenEstudio(
            orden=orden, tipo_estudio=tipo_estudio, subida_por=usuario,
            huella_sha256=hashlib.sha256(contenido_original).hexdigest(),
        )
        nueva_imagen.archivo.save(jpg_convertido.name, jpg_convertido, save=False)
        nombre_original = archivo.name if '.' in archivo.name else f'{archivo.name}.dcm'
        nueva_imagen.archivo_original.save(
            nombre_original, ContentFile(contenido_original), save=False
        )
        nueva_imagen.save()
        return True
    # No se pudo convertir (no era un DICOM válido): se omite en silencio,
    # es habitual que una carpeta traiga archivos que no son parte del estudio.
    return False


def _tipo_estudio_del_combo(orden, tipo_estudio_id):
    """Valida que `tipo_estudio_id` sea uno de los estudios de esta cita
    (ver Cita.estudios) y lo devuelve, o None si no corresponde."""
    for estudio in orden.cita.estudios:
        if str(estudio.id) == str(tipo_estudio_id):
            return estudio
    return None


@login_required
@user_passes_test(es_tecnico)
def adjuntar_imagenes(request, orden_id):
    """Pantalla de carga: un bloque por cada estudio de la cita (uno solo si
    no es un combo, ver Cita.estudios). El envío real (y la barra de
    progreso) los maneja el JS del template llamando a
    adjuntar_imagenes_lote/_finalizar en tandas, por bloque; este POST solo
    queda como respaldo por si el navegador no ejecuta JavaScript."""
    orden = get_object_or_404(sucursales.permitidas(OrdenTrabajo.objects, request.user, 'cita__sucursal'), id=orden_id, cita__estado=Cita.ESTADO_EN_PROCESO)
    volver_url = reverse('ordenes_pendientes')
    estudios = orden.cita.estudios

    if request.method == 'POST':
        if not orden.esta_verificada:
            messages.error(request, MENSAJE_VERIFICAR_ESTUDIO)
            return redirect('adjuntar_imagenes', orden_id=orden.id)
        form = AdjuntarImagenesForm(request.POST, request.FILES)
        if form.is_valid():
            tipo_estudio = form.cleaned_data['tipo_estudio']
            if tipo_estudio not in estudios:
                messages.error(request, 'Ese estudio no corresponde a esta orden.')
                return redirect('adjuntar_imagenes', orden_id=orden.id)
            archivos = form.cleaned_data['imagenes']
            adjuntadas = sum(
                _guardar_imagen_o_convertir_dicom(archivo, orden, request.user, tipo_estudio)
                for archivo in archivos
            )

            if adjuntadas == 0:
                messages.error(
                    request,
                    'No se encontraron imágenes ni archivos DICOM válidos en lo seleccionado.',
                )
                return redirect('adjuntar_imagenes', orden_id=orden.id)

            _notificar_estudio_listo_para_informar(orden.cita)
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_ADJUNTAR_IMAGENES,
                descripcion=(
                    f'Adjuntó {adjuntadas} imagen(es) de {tipo_estudio.nombre} a la orden de '
                    f'{orden.cita.paciente} (orden #{orden.id}).'
                ),
            )
            if orden.imagenes_completas:
                messages.success(
                    request,
                    f'Imágenes adjuntadas para {orden.cita.paciente}. Ya está lista para la radióloga.',
                )
                return redirect(volver_url)
            messages.success(
                request,
                f'Imágenes de {tipo_estudio.nombre} adjuntadas. Todavía falta cargar el resto del combo.',
            )
            return redirect('adjuntar_imagenes', orden_id=orden.id)

    bloques = [
        {
            'tipo_estudio': estudio,
            'imagenes': orden.imagenes.filter(tipo_estudio=estudio),
            'form': AdjuntarImagenesForm(initial={'tipo_estudio': estudio.id}),
        }
        for estudio in estudios
    ]

    return render(request, 'pacientes/adjuntar_imagenes.html', {
        'form_modificacion': SolicitarModificacionEstudioForm(),
        'cita': orden.cita,
        'orden': orden,
        'edad': orden.edad_paciente,
        'volver_url': volver_url,
        'bloques': bloques,
    })


@login_required
@user_passes_test(es_tecnico)
@require_POST
def adjuntar_imagenes_lote(request, orden_id):
    """Guarda una tanda de archivos de la carpeta que está subiendo el
    técnico, para un estudio puntual de la cita (`tipo_estudio` en el POST).
    El JS de adjuntar_imagenes.html llama a esta vista una vez por tanda (en
    vez de mandar la carpeta entera en un solo POST) para poder mostrar una
    barra de progreso real mientras se procesan los DICOM."""
    orden = get_object_or_404(sucursales.permitidas(OrdenTrabajo.objects, request.user, 'cita__sucursal'), id=orden_id, cita__estado=Cita.ESTADO_EN_PROCESO)
    if not orden.esta_verificada:
        return JsonResponse({'ok': False, 'error': MENSAJE_VERIFICAR_ESTUDIO}, status=403)
    tipo_estudio = _tipo_estudio_del_combo(orden, request.POST.get('tipo_estudio'))
    if tipo_estudio is None:
        return JsonResponse({'ok': False, 'error': 'Estudio no válido para esta orden.'}, status=400)
    archivos = request.FILES.getlist('imagenes')
    guardadas = 0
    for archivo in archivos:
        nombre = archivo.name.lower()
        if nombre.startswith('.') or nombre.endswith(NOMBRES_IGNORADOS_EN_CARPETA):
            continue
        if _guardar_imagen_o_convertir_dicom(archivo, orden, request.user, tipo_estudio):
            guardadas += 1
    return JsonResponse({'guardadas': guardadas, 'recibidas': len(archivos)})


@login_required
@user_passes_test(es_tecnico)
@require_POST
def adjuntar_imagenes_finalizar(request, orden_id):
    """Cierra la carga de un estudio puntual de la cita después de que el JS
    terminó de mandar todas las tandas: notifica a la radióloga y registra
    la bitácora. Solo manda de vuelta a "Órdenes pendientes" cuando YA
    quedaron cargados todos los estudios de la cita (ver
    OrdenTrabajo.imagenes_completas); si es un combo y todavía falta otro
    estudio, se queda en la misma pantalla para seguir cargando."""
    orden = get_object_or_404(sucursales.permitidas(OrdenTrabajo.objects, request.user, 'cita__sucursal'), id=orden_id, cita__estado=Cita.ESTADO_EN_PROCESO)
    if not orden.esta_verificada:
        return JsonResponse({'ok': False, 'error': MENSAJE_VERIFICAR_ESTUDIO}, status=403)
    tipo_estudio = _tipo_estudio_del_combo(orden, request.POST.get('tipo_estudio'))
    if tipo_estudio is None:
        return JsonResponse({'ok': False, 'error': 'Estudio no válido para esta orden.'}, status=400)
    adjuntadas = orden.imagenes.filter(tipo_estudio=tipo_estudio).count()

    if adjuntadas == 0:
        return JsonResponse(
            {'ok': False, 'error': 'No se encontraron imágenes ni archivos DICOM válidos en lo seleccionado.'},
            status=400,
        )

    _notificar_estudio_listo_para_informar(orden.cita)
    Bitacora.registrar(
        request=request,
        usuario=request.user,
        accion=Bitacora.ACCION_ADJUNTAR_IMAGENES,
        descripcion=(
            f'Adjuntó {adjuntadas} imagen(es) de {tipo_estudio.nombre} a la orden de '
            f'{orden.cita.paciente} (orden #{orden.id}).'
        ),
    )
    completo = orden.imagenes_completas
    if completo:
        messages.success(
            request, f'Imágenes adjuntadas para {orden.cita.paciente}. Ya está lista para la radióloga.'
        )
    return JsonResponse({
        'ok': True,
        'completo': completo,
        'redirect_url': reverse('ordenes_pendientes') if completo else None,
    })


@login_required
@user_passes_test(es_tecnico)
@require_POST
def validar_estudio(request, orden_id):
    """El técnico revisa los datos del estudio antes de cargar las imágenes:
    "Estudio correcto" deja el cobro listo para Caja; "Modificar estudio" le
    pide a recepción que cambie algo (ver corregir_estudio_cita)."""
    orden = get_object_or_404(
        sucursales.permitidas(OrdenTrabajo.objects.select_related('cita__paciente', 'cita__tipo_estudio'), request.user, 'cita__sucursal'),
        id=orden_id, cita__estado=Cita.ESTADO_EN_PROCESO,
    )
    cita = orden.cita
    volver = redirect('adjuntar_imagenes', orden_id=orden.id)

    if orden.validacion_estado == OrdenTrabajo.VALIDACION_CORRECTO:
        messages.info(request, 'Este estudio ya está confirmado como correcto.')
        return volver
    if orden.validacion_estado == OrdenTrabajo.VALIDACION_MODIFICACION:
        messages.info(
            request,
            'Ya le pediste a recepción que modifique este estudio. Esperá a que lo actualice.',
        )
        return volver

    accion = request.POST.get('accion')
    if accion == 'correcto':
        orden.validacion_estado = OrdenTrabajo.VALIDACION_CORRECTO
        orden.validacion_por = request.user
        orden.validacion_en = timezone.now()
        orden.save(update_fields=['validacion_estado', 'validacion_por', 'validacion_en'])
        _notificar_estudio_validado(cita)
        Bitacora.registrar(
            request=request, usuario=request.user,
            accion=Bitacora.ACCION_VALIDAR_ESTUDIO,
            descripcion=(
                f'Confirmó que el estudio {cita.tipo_estudio} de {cita.paciente} '
                f'(cita #{cita.id}) es correcto.'
            ),
        )
        messages.success(
            request, 'Estudio confirmado como correcto. Recepción ya puede cobrarlo; cargá las imágenes.',
        )
    elif accion == 'modificar':
        form = SolicitarModificacionEstudioForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Indicá qué hay que modificar del estudio.')
            return volver
        nota = form.cleaned_data['nota']
        orden.validacion_estado = OrdenTrabajo.VALIDACION_MODIFICACION
        orden.validacion_nota = nota
        orden.validacion_por = request.user
        orden.validacion_en = timezone.now()
        orden.correccion_detalle = ''
        orden.save(update_fields=[
            'validacion_estado', 'validacion_nota', 'validacion_por', 'validacion_en',
            'correccion_detalle',
        ])
        _notificar_modificacion_solicitada(cita, nota)
        Bitacora.registrar(
            request=request, usuario=request.user,
            accion=Bitacora.ACCION_SOLICITAR_MODIFICACION,
            descripcion=(
                f'Pidió modificar el estudio {cita.tipo_estudio} de {cita.paciente} '
                f'(cita #{cita.id}): {nota}'
            ),
        )
        messages.success(request, 'Se le avisó a recepción. Cuando lo actualicen te va a aparecer aquí.')
    else:
        messages.error(request, 'Acción no válida.')
    return volver


def _volver_de_recepcion(cita):
    """URL a la que vuelve recepción tras corregir un estudio: la agenda del día
    en COEX/Privado, o la Pantalla de turnos en Emergencia IGSS."""
    if cita.convenio in (Cita.CONVENIO_COEX, Cita.CONVENIO_PRIVADO):
        return f'{reverse(f"procesar_citas_{cita.convenio}")}?fecha={cita.fecha}'
    return reverse('pantalla_turnos')


@login_required
@user_passes_test(es_recepcionista)
def estudios_por_corregir(request):
    """Estudios que el técnico pidió modificar y recepción todavía no
    actualizó, sin importar la fecha ni el convenio."""
    ordenes = (
        sucursales.filtrar(OrdenTrabajo.objects.filter(
            cita__estado=Cita.ESTADO_EN_PROCESO,
            validacion_estado=OrdenTrabajo.VALIDACION_MODIFICACION,
        ), request, 'cita__sucursal')
        .select_related('cita__paciente', 'cita__tipo_estudio', 'validacion_por')
        .order_by('validacion_en')
    )
    return render(request, 'pacientes/estudios_por_corregir.html', {'ordenes': ordenes})


@login_required
@user_passes_test(es_recepcionista)
def corregir_estudio_cita(request, cita_id):
    """Recepción hace el cambio que pidió el técnico (otro estudio, otro
    radiólogo o la indicación clínica) y le avisa que ya está actualizado."""
    cita = get_object_or_404(
        sucursales.permitidas(Cita.objects.select_related('paciente', 'tipo_estudio', 'radiologo'), request.user),
        id=cita_id, estado=Cita.ESTADO_EN_PROCESO, orden_trabajo__isnull=False,
    )
    orden = cita.orden_trabajo
    if orden.validacion_estado != OrdenTrabajo.VALIDACION_MODIFICACION:
        messages.info(request, 'Este estudio no tiene ninguna modificación pendiente.')
        return redirect(_volver_de_recepcion(cita))

    if request.method == 'POST':
        form = CorregirEstudioForm(request.POST, cita=cita)
        if form.is_valid():
            cd = form.cleaned_data
            nuevo = cd['tipo_estudio']
            cambio_estudio = nuevo.id != cita.tipo_estudio_id
            if cambio_estudio and _hay_estudio_duplicado(
                dpi=cita.paciente.dpi, tipo_estudio=nuevo, fecha=cita.fecha, hora=cita.hora,
            ):
                form.add_error(
                    'tipo_estudio',
                    'Este paciente ya tiene agendado ese mismo estudio en la misma fecha y hora.',
                )
            else:
                cambios = []
                if cambio_estudio:
                    cambios.append(f'Estudio: {cita.tipo_estudio.nombre} → {nuevo.nombre}')
                radiologo = cd.get('radiologo')
                if radiologo and radiologo.id != cita.radiologo_id:
                    cambios.append(f'Radiólogo: {radiologo.get_full_name() or radiologo.username}')
                if cd['motivo'].strip() != orden.motivo.strip():
                    cambios.append('Indicación clínica actualizada')
                if cd['comentario']:
                    cambios.append(cd['comentario'])
                detalle = '; '.join(cambios) or 'Datos revisados, sin cambios'

                estudio_anterior = cita.tipo_estudio
                cita.tipo_estudio = nuevo
                if radiologo:
                    cita.radiologo = radiologo
                cita.save(update_fields=['tipo_estudio', 'radiologo'])
                orden.motivo = cd['motivo'].strip()
                orden.validacion_estado = OrdenTrabajo.VALIDACION_CORREGIDO
                orden.correccion_detalle = detalle[:255]
                orden.correccion_por = request.user
                orden.correccion_en = timezone.now()
                orden.save(update_fields=[
                    'motivo', 'validacion_estado', 'correccion_detalle',
                    'correccion_por', 'correccion_en',
                ])
                _notificar_estudio_actualizado(orden)
                sufijo = f' (antes: {estudio_anterior.nombre}).' if cambio_estudio else '.'
                Bitacora.registrar(
                    request=request, usuario=request.user,
                    accion=Bitacora.ACCION_CORREGIR_ESTUDIO,
                    descripcion=(
                        f'Modificó el estudio de {cita.paciente} (cita #{cita.id}) a pedido del '
                        f'técnico: {detalle}{sufijo}'
                    ),
                )
                messages.success(
                    request, f'Estudio actualizado. Se le avisó al técnico de {cita.paciente}.',
                )
                return redirect(_volver_de_recepcion(cita))
    else:
        form = CorregirEstudioForm(
            cita=cita,
            initial={
                'tipo_estudio': cita.tipo_estudio_id,
                'radiologo': cita.radiologo_id,
                'motivo': orden.motivo,
            },
        )

    return render(request, 'pacientes/corregir_estudio.html', {
        'form': form,
        'cita': cita,
        'orden': orden,
        'edad': cita.paciente.edad_en(cita.fecha),
        'volver_url': reverse('estudios_por_corregir'),
    })


@login_required
@user_passes_test(es_radiologo)
def citas_procesadas(request):
    """Bandeja del radiólogo: estudios EN_PROCESO que ya tienen imágenes y
    esperan informe. Filtra por texto, convenio y si vienen en una orden de
    pago agrupada."""
    busqueda = (request.GET.get('q') or '').strip()
    convenio = (request.GET.get('convenio') or '').strip()
    agrupacion = (request.GET.get('agrupacion') or '').strip()
    ordenes = (
        sucursales.filtrar(
            OrdenTrabajo.objects.filter(cita__estado=Cita.ESTADO_EN_PROCESO, imagenes__isnull=False),
            request, 'cita__sucursal',
        )
        .select_related('cita', 'cita__paciente', 'cita__tipo_estudio')
        .prefetch_related('cita__detalles_orden_pago__orden_pago__combo')
        .distinct()
        .order_by('creada_en')
    )
    if busqueda:
        ordenes = ordenes.filter(
            Q(cita__paciente__nombre__icontains=busqueda)
            | Q(cita__paciente__apellido__icontains=busqueda)
            | Q(cita__paciente__dpi__icontains=busqueda)
            | Q(cita__paciente__telefono__icontains=busqueda)
        )
    if convenio in dict(Cita.CONVENIO_CHOICES):
        ordenes = ordenes.filter(cita__convenio=convenio)
    if agrupacion == 'agrupado':
        ordenes = ordenes.filter(cita__detalles_orden_pago__isnull=False)
    elif agrupacion == 'individual':
        ordenes = ordenes.filter(cita__detalles_orden_pago__isnull=True)
    for orden in ordenes:
        orden.es_agrupada = bool(orden.cita.detalles_orden_pago.all())
    return render(request, 'pacientes/citas_procesadas.html', {
        'ordenes': ordenes,
        'busqueda': busqueda,
        'convenio': convenio,
        'agrupacion': agrupacion,
        'convenios': Cita.CONVENIO_CHOICES,
    })


@login_required
@user_passes_test(es_radiologo)
def adjuntar_informe(request, cita_id):
    """El radiólogo sube/redacta el informe de cada estudio de la cita (un combo
    tiene varios) y opcionalmente agrega un estudio extra. Cuando todos los
    estudios tienen informe la cita queda PROCESADA y se intenta el envío
    automático de resultados al paciente y al médico tratante."""
    cita = get_object_or_404(sucursales.permitidas(Cita.objects, request.user), id=cita_id, estado=Cita.ESTADO_EN_PROCESO)
    orden = get_object_or_404(sucursales.permitidas(OrdenTrabajo.objects, request.user, 'cita__sucursal'), cita=cita)
    if not orden.tiene_imagenes:
        messages.error(request, 'El técnico todavía no adjunta las imágenes de este estudio.')
        return redirect('citas_procesadas')
    volver_url = reverse('citas_procesadas')
    puede_agregar_extra = cita.convenio in (
        Cita.CONVENIO_PRIVADO,
        Cita.CONVENIO_COEX,
        Cita.CONVENIO_EMERGENCIA_IGSS,
    )

    estudios = cita.estudios
    informes_por_estudio = {i.tipo_estudio_id: i for i in orden.informes.all()}

    if request.method == 'POST':
        form = AdjuntarInformeForm(request.POST, request.FILES, estudios=estudios)
        # El estudio extra se agrega en el mismo envío que el informe (no
        # tiene su propio botón): solo se valida/crea si de verdad se eligió
        # uno, para no exigirlo cuando el radiólogo solo quiere guardar el
        # informe.
        form_estudio_extra = None
        if puede_agregar_extra and request.POST.get('tipo_estudio'):
            form_estudio_extra = AgregarEstudioExtraForm(request.POST)

        if form.is_valid() and (form_estudio_extra is None or form_estudio_extra.is_valid()):
            guardados = []
            for estudio in estudios:
                texto, archivo = form.valores_para(estudio)
                if not texto and not archivo:
                    continue
                defaults = {'creado_por': request.user, 'creado_en': timezone.now()}
                if texto:
                    defaults['texto'] = texto
                if archivo:
                    defaults['archivo'] = archivo
                InformeEstudio.objects.update_or_create(orden=orden, tipo_estudio=estudio, defaults=defaults)
                guardados.append(estudio.nombre)

            if form_estudio_extra is not None:
                _registrar_estudio_extra(request, cita, form_estudio_extra)

            # cita.estudios (no `estudios`, que es el snapshot de antes de
            # registrar el extra) para que un estudio extra recién marcado
            # "procesar ahora" cuente como pendiente y la cita NO pase a
            # PROCESADA hasta que también tenga su informe -- si no se
            # marcó "procesar ahora" (o no se agregó ninguno), cita.estudios
            # da exactamente lo mismo que `estudios` y no cambia nada.
            completos_ids = {i.tipo_estudio_id for i in orden.informes.all() if i.texto or i.archivo}
            faltan = [e.nombre for e in cita.estudios if e.id not in completos_ids]
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_ADJUNTAR_INFORME,
                descripcion=(
                    f'Adjuntó el informe de {", ".join(guardados)} para {cita.paciente} (cita #{cita.id})'
                    + ('.' if not faltan else f'; todavía falta: {", ".join(faltan)}.')
                ),
            )
            if not faltan:
                cita.estado = Cita.ESTADO_PROCESADA
                cita.save(update_fields=['estado'])
                _notificar_estudio_completado(cita)
                _intentar_envio_medico_tratante(request, cita, orden)
                if not _intentar_envio_automatico(request, cita):
                    messages.success(request, f'Informe completo para {cita.paciente}. Ya se puede enviar al paciente.')
            else:
                messages.success(
                    request,
                    f'Informe guardado para {cita.paciente}. Todavía falta: {", ".join(faltan)}.',
                )
            return redirect(volver_url)
    else:
        initial = {
            f'texto_{estudio.id}': informes_por_estudio[estudio.id].texto
            for estudio in estudios
            if estudio.id in informes_por_estudio and informes_por_estudio[estudio.id].texto
        }
        form = AdjuntarInformeForm(estudios=estudios, initial=initial)
        form_estudio_extra = AgregarEstudioExtraForm() if puede_agregar_extra else None

    bloques = [
        {
            'tipo_estudio': estudio,
            'tiene_imagenes': orden.imagenes.filter(tipo_estudio=estudio).exists(),
            'informe': informes_por_estudio.get(estudio.id),
            'campo_texto': form[f'texto_{estudio.id}'],
            'campo_archivo': form[f'archivo_{estudio.id}'],
        }
        for estudio in estudios
    ]

    return render(request, 'pacientes/adjuntar_informe.html', {
        'form': form,
        'cita': cita,
        'orden': orden,
        'edad': cita.paciente.edad_en(cita.fecha),
        'volver_url': volver_url,
        'bloques': bloques,
        'tiene_dicom_original': any(img.archivo_original for img in orden.imagenes.all()),
        'form_estudio_extra': form_estudio_extra,
        'puede_agregar_extra': puede_agregar_extra,
        'estudios_extra': cita.estudios_extra.select_related('tipo_estudio', 'agregado_por').all(),
    })


def _registrar_estudio_extra(request, cita, form):
    """Crea el EstudioExtra a partir de un form ya validado y lo registra en
    la bitácora. Lo usan tanto agregar_estudio_extra (el endpoint viejo,
    standalone) como adjuntar_informe (cuando se agrega en el mismo envío
    que el informe).

    Por sí solo (sin "procesar ahora") es solo una sugerencia: no se cobra
    ni se reabre el cobro, no se avisa a recepción/técnico, y no entra a
    Cita.estudios (ver EstudioExtra). El paciente y el médico tratante se
    enteran de la sugerencia al entrar a su visor de resultados (ver
    visor_estudio), no por una notificación aparte.

    Si queda marcado "procesar ahora", en cambio, sí se cobra de una vez
    (reabre el cobro si ya estaba pagado) y se avisa a recepción y al
    técnico -- a partir de acá entra a Cita.estudios y aparece como trabajo
    pendiente en su pantalla, igual que un estudio de combo."""
    extra = EstudioExtra.objects.create(
        cita=cita,
        tipo_estudio=form.cleaned_data['tipo_estudio'],
        agregado_por=request.user,
        notas=form.cleaned_data['notas'],
        procesar_ahora=form.cleaned_data['procesar_ahora'],
    )
    if extra.procesar_ahora:
        cobro, _ = Cobro.objects.get_or_create(cita=cita)
        if cobro.estado == Cobro.ESTADO_PAGADO:
            cobro.estado = Cobro.ESTADO_PENDIENTE
            cobro.pagado_en = None
            cobro.cobrado_por = None
            cobro.forma_pago = ''
            cobro.numero_boleta = ''
            cobro.comprobante_bancario = None
            cobro.notas = 'Ajuste pendiente por estudio extra agregado.'
            cobro.save(update_fields=[
                'estado', 'pagado_en', 'cobrado_por', 'forma_pago', 'numero_boleta',
                'comprobante_bancario', 'notas',
            ])
        mensaje = (
            f'{request.user.get_full_name() or request.user.username} agregó el estudio extra '
            f'"{extra.tipo_estudio.nombre}" (Q{extra.precio:.2f}) para {cita.paciente.nombre} '
            f'{cita.paciente.apellido}.'
        )
        recepcionistas = Usuario.objects.filter(rol=Usuario.ROL_RECEPCIONISTA, is_active=True)
        Notificacion.notificar_a_varios(
            usuarios=recepcionistas,
            tipo=Notificacion.TIPO_ESTUDIO_EXTRA_AGREGADO,
            mensaje=mensaje,
            cita=cita,
            url=reverse('pagos_pendientes'),
        )
        _notificar_orden_pendiente(cita)
    Bitacora.registrar(
        request=request,
        usuario=request.user,
        accion=Bitacora.ACCION_AGREGAR_ESTUDIO_EXTRA,
        descripcion=(
            f'Agregó el estudio extra "{extra.tipo_estudio.nombre}" (Q{extra.precio:.2f}) '
            f'a la cita de {cita.paciente} (cita #{cita.id})'
            + (', marcado para procesar ahora.' if extra.procesar_ahora else ', como sugerencia.')
        ),
    )
    return extra


@login_required
@user_passes_test(es_radiologo)
@require_POST
def agregar_estudio_extra(request, cita_id):
    """El radiólogo avisa que le realizó al paciente un estudio extra al
    agendado. Caja lo cobra directamente o lo agrupa según el convenio."""
    cita = get_object_or_404(
        sucursales.permitidas(Cita.objects, request.user),
        id=cita_id,
        convenio__in=(
            Cita.CONVENIO_PRIVADO,
            Cita.CONVENIO_COEX,
            Cita.CONVENIO_EMERGENCIA_IGSS,
        ),
        estado=Cita.ESTADO_EN_PROCESO,
    )
    volver_url = reverse('adjuntar_informe', args=[cita.id])
    form = AgregarEstudioExtraForm(request.POST)
    if not form.is_valid() or not form.cleaned_data.get('tipo_estudio'):
        messages.error(request, 'Elegí un estudio válido para agregarlo como extra.')
        return redirect(volver_url)

    extra = _registrar_estudio_extra(request, cita, form)
    if extra.procesar_ahora:
        mensaje = f'Estudio extra "{extra.tipo_estudio.nombre}" agregado y notificado a recepción.'
    else:
        mensaje = (
            f'Estudio extra "{extra.tipo_estudio.nombre}" agregado como sugerencia: el paciente y '
            'el médico tratante la van a ver al entrar a su visor de resultados.'
        )
    messages.success(request, mensaje)
    return redirect(volver_url)


@login_required
@user_passes_test(es_radiologo)
@xframe_options_sameorigin
def ver_imagenes_jpg(request, orden_id):
    """Galería con las imágenes JPG (ya convertidas si venían de DICOM) de
    un estudio, con casillas para que la radióloga elija cuáles quedan: las
    que deje marcadas son las que se siguen viendo y las que se le envían
    al paciente por correo; las que desmarque se borran de acá (el JPG),
    pero si tenían un DICOM detrás ese se conserva completo sin tocar. Se
    muestra en un <iframe> dentro de adjuntar_informe.html (no en una
    pestaña aparte, para no arriesgar el PDF del informe ya elegido —
    ver el comentario en ese template); @xframe_options_sameorigin permite
    que el navegador la deje incrustar ahí."""
    orden = get_object_or_404(sucursales.permitidas(OrdenTrabajo.objects, request.user, 'cita__sucursal'), id=orden_id)
    imagenes = orden.imagenes.filter(seleccionada=True).exclude(archivo='')
    # Si viene de un bloque puntual de adjuntar_informe (un estudio del
    # combo), filtra la galería a ese estudio; sin el parámetro muestra
    # todas, como antes.
    tipo_estudio_id = request.GET.get('tipo_estudio')
    if tipo_estudio_id:
        imagenes = imagenes.filter(tipo_estudio_id=tipo_estudio_id)
    return render(request, 'pacientes/ver_imagenes_jpg.html', {
        'orden': orden,
        'cita': orden.cita,
        'imagenes': imagenes,
    })


def _borrar_archivo_media(storage, nombre, intentos=5):
    """Borra un archivo del storage tolerando el bloqueo temporal de Windows
    (WinError 5 / PermissionError) que aparece cuando otro hilo lo está
    sirviendo o el antivirus lo está escaneando. Reintenta con una pausa
    corta; si aun así no se pudo, devuelve False y el archivo queda huérfano
    en disco (no rompe la operación; se puede limpiar aparte)."""
    if not nombre:
        return True
    for intento in range(intentos):
        try:
            storage.delete(nombre)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if intento < intentos - 1:
                time.sleep(0.3 * (intento + 1))
    return False


@login_required
@user_passes_test(es_radiologo)
@require_POST
def guardar_seleccion_imagenes(request, orden_id):
    """Aplica la selección hecha en ver_imagenes_jpg.html: descarta el JPG
    de las imágenes que quedaron sin marcar. Si esa imagen venía de un
    DICOM, el .dcm original se conserva íntegro (solo se le borra el JPG y
    se le apaga "seleccionada"); si no tenía DICOM detrás (se subió como
    JPG/PNG directo), no queda nada que conservar y se elimina del todo.

    El estado en la base de datos se actualiza siempre; borrar el archivo
    físico es "mejor esfuerzo" (ver _borrar_archivo_media) para no reventar
    si Windows lo tiene bloqueado un instante."""
    orden = get_object_or_404(sucursales.permitidas(OrdenTrabajo.objects, request.user, 'cita__sucursal'), id=orden_id)
    ids_marcados = set(request.POST.getlist('seleccionadas'))

    descartadas = 0
    huerfanos = 0
    for imagen in orden.imagenes.filter(seleccionada=True).exclude(archivo=''):
        if str(imagen.id) in ids_marcados:
            continue
        descartadas += 1
        storage = imagen.archivo.storage
        nombre_jpg = imagen.archivo.name
        try:
            imagen.archivo.close()
        except Exception:
            pass

        if imagen.archivo_original:
            imagen.archivo = ''
            imagen.seleccionada = False
            imagen.save(update_fields=['archivo', 'seleccionada'])
        else:
            imagen.delete()

        if not _borrar_archivo_media(storage, nombre_jpg):
            huerfanos += 1

    if descartadas:
        Bitacora.registrar(
            request=request,
            usuario=request.user,
            accion=Bitacora.ACCION_SELECCIONAR_IMAGENES,
            descripcion=(
                f'Descartó {descartadas} imagen(es) de la galería de la orden #{orden.id} '
                f'({orden.cita.paciente}).'
            ),
        )
        messages.success(request, f'Se descartaron {descartadas} imagen(es) de la galería.')
        if huerfanos:
            messages.warning(
                request,
                f'{huerfanos} archivo(s) no se pudieron borrar del disco en este momento '
                '(estaban en uso); ya no aparecen en la galería.',
            )
    else:
        messages.info(request, 'No se descartó ninguna imagen.')

    # Antes volvía a adjuntar_informe; ahora que esta pantalla se muestra
    # en un <iframe> dentro de esa misma página (ver el comentario en
    # ver_imagenes_jpg), tiene que quedarse en la galería en vez de intentar
    # cargar la página completa de "arriba" adentro del iframe.
    return redirect('ver_imagenes_jpg', orden_id=orden.id)


@login_required
@user_passes_test(es_radiologo)
def descargar_dicom_orden(request, orden_id):
    """Empaqueta en un .zip los archivos DICOM originales (los que el
    técnico subió y se convirtieron a JPG) de un estudio, para que la
    radióloga los baje a su equipo desde el botón "Descargar DICOM"."""
    orden = get_object_or_404(sucursales.permitidas(OrdenTrabajo.objects, request.user, 'cita__sucursal'), id=orden_id)
    imagenes_con_dicom = [img for img in orden.imagenes.all() if img.archivo_original]

    if not imagenes_con_dicom:
        messages.error(request, 'Este estudio no tiene archivos DICOM originales para descargar.')
        return redirect('adjuntar_informe', cita_id=orden.cita_id)

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_archivo:
        nombres_usados = set()
        for imagen in imagenes_con_dicom:
            nombre = os.path.basename(imagen.archivo_original.name)
            base, ext = os.path.splitext(nombre)
            candidato = nombre
            contador = 1
            # Evita pisar archivos dentro del zip si dos vinieran con el
            # mismo nombre (ej. "I0" en dos series distintas).
            while candidato in nombres_usados:
                candidato = f'{base}_{contador}{ext}'
                contador += 1
            nombres_usados.add(candidato)
            with imagen.archivo_original.open('rb') as contenido:
                zip_archivo.writestr(candidato, contenido.read())
    buffer.seek(0)

    nombre_zip = f'dicom_{orden.cita.paciente.dpi}_orden{orden.id}.zip'
    respuesta = HttpResponse(buffer.getvalue(), content_type='application/zip')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre_zip}"'
    return respuesta
