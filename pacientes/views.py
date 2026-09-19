import base64
import binascii
import datetime
import os
import time
import zipfile
from decimal import Decimal
from io import BytesIO

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.dateparse import parse_date
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from accounts.models import MESES_ES, Bitacora, Usuario
from accounts.views import es_administrador
from clinica.validators import avisar_si_correo_no_existe
from django.utils.text import slugify
from .correos import enviar_resultados
from .dicom_utils import dicom_a_jpg_memoria
from .forms import (
    AdjuntarImagenesForm,
    AdjuntarInformeForm,
    AgendarCitaForm,
    AgendarCitaPrivadoForm,
    AgregarEstudioExtraForm,
    ComboForm,
    CompletarDatosPacienteForm,
    CorregirEstudioForm,
    CrearTipoEstudioForm,
    CrearOrdenPagoForm,
    EXTENSIONES_IMAGEN_DIRECTA,
    GenerarOrdenForm,
    IngresarCorreoEnvioForm,
    NOMBRES_IGNORADOS_EN_CARPETA,
    ProcesarTicketForm,
    RegistrarPagoEstudioForm,
    RegistrarTicketForm,
    SolicitarModificacionEstudioForm,
    SubirConstanciaFirmadaForm,
)
from .horarios import (
    DIAS_SEMANA,
    LIMITE_DIAS_ADELANTE,
    PASO_MINUTOS,
    en_el_pasado,
    fuera_de_ventana,
    horarios_disponibles,
    inicio_semana,
    rango_ocupado_por,
    se_cruzan,
)
from .models import (
    Cita,
    Cobro,
    Combo,
    EstudioExtra,
    HistorialModalidad,
    HistorialPrecioEstudio,
    ImagenEstudio,
    InformeEstudio,
    Modalidad,
    Notificacion,
    OrdenPago,
    DetalleOrdenPago,
    OrdenTrabajo,
    Paciente,
    ReporteDiario,
    Ticket,
    TipoEstudio,
)


MENSAJE_VERIFICAR_ESTUDIO = (
    'Antes de cargar las imágenes, confirmá si el estudio es el correcto o pedile '
    'a recepción que lo modifique.'
)

# Cuántas citas de emergencia (agendadas encima de otra ya existente) se
# permiten como máximo por día, para no saturar a la radióloga.
MAXIMO_EMERGENCIAS_POR_DIA = 5

# Etiqueta corta del convenio para mostrar en las celdas del calendario.
ETIQUETA_CONVENIO_CORTA = {
    Cita.CONVENIO_COEX: 'COEX',
    Cita.CONVENIO_PRIVADO: 'Privado',
    Cita.CONVENIO_EMERGENCIA_IGSS: 'Emerg. IGSS',
}

# Datos de la clínica que salen en la boleta / recibo de pago. Editar acá.
CLINICA_NOMBRE = 'Clínica de Imágenes'
CLINICA_RUBRO = 'Estudios de radiología e imágenes diagnósticas'
CLINICA_DIRECCION = 'Av. XXXXXXXXXXXXXXXX, zona X, Ciudad de Guatemala'
CLINICA_TELEFONO = 'XXXX-XXXX'


def es_recepcionista(user):
    return user.is_authenticated and user.tiene_rol(Usuario.ROL_RECEPCIONISTA)


def es_caja(user):
    """Puede operar la pantalla de Caja: por el permiso puede_operar_caja
    (independiente del rol) o por ser administrador. Portado (2026-09-04)
    desde la rama visual-andres de TechBlood."""
    return user.is_authenticated and (user.puede_operar_caja or es_administrador(user))


def puede_ver_comprobante_pago(user):
    """Personal autorizado a consultar el comprobante de un estudio pagado.
    HU-50/HU-52 (portado 2026-09-12 desde la rama visual-andres de
    TechBlood): además de Caja/administración, recepción, técnicos y
    radiólogos necesitan poder revisar la boleta/constancia mientras
    trabajan la orden."""
    return user.is_authenticated and (
        es_administrador(user)
        or es_caja(user)
        or any(
            user.tiene_rol(rol) for rol in (
                Usuario.ROL_RECEPCIONISTA,
                Usuario.ROL_TECNICO_IMAGENES,
                Usuario.ROL_MEDICO_RADIOLOGO,
            )
        )
    )


def es_tecnico(user):
    return user.is_authenticated and user.tiene_rol(Usuario.ROL_TECNICO_IMAGENES)


def es_radiologo(user):
    return user.is_authenticated and user.tiene_rol(Usuario.ROL_MEDICO_RADIOLOGO)


def es_administrador_financiero(user):
    return user.is_authenticated and (
        user.is_superuser or user.tiene_rol(Usuario.ROL_ADMINISTRADOR_FINANCIERO)
    )


def puede_ver_reportes_diarios(user):
    return es_recepcionista(user) or es_administrador_financiero(user) or es_administrador(user)


def puede_descargar_reportes_diarios(user):
    return es_administrador_financiero(user) or es_administrador(user)


def _notificar_cita_asignada(cita):
    """El radiólogo elegido al agendar la cita recibe una nueva solicitud
    para revisar/confirmar. Si la recepcionista la marcó como emergencia
    (agendada encima de otra cita ya existente), el mensaje lo deja claro
    para que la radióloga sepa que se le está pidiendo hacer un espacio."""
    prefijo = '🚨 EMERGENCIA — ' if cita.es_emergencia_forzada else ''
    mensaje = (
        f'{prefijo}Nueva cita asignada: {cita.tipo_estudio} para {cita.paciente.nombre} '
        f'{cita.paciente.apellido} el {cita.fecha_sugerida or cita.fecha} a las '
        f'{cita.hora_sugerida or cita.hora}.'
    )
    if cita.es_emergencia_forzada:
        mensaje += ' Este horario ya tenía otra cita asignada: se agendó igual por ser una emergencia.'
    Notificacion.notificar(
        destinatario=cita.radiologo,
        tipo=Notificacion.TIPO_CITA_ASIGNADA,
        mensaje=mensaje,
        cita=cita,
        url=reverse('solicitudes_pendientes'),
    )


def _notificar_cita_confirmada(cita):
    """El radiólogo confirmó fecha/hora de la solicitud: se avisa a quien
    la creó (recepción) para que pueda comunicárselo al paciente."""
    Notificacion.notificar(
        destinatario=cita.creada_por,
        tipo=Notificacion.TIPO_CITA_CONFIRMADA,
        mensaje=(
            f'Cita confirmada: {cita.tipo_estudio} de {cita.paciente.nombre} '
            f'{cita.paciente.apellido} el {cita.fecha} a las {cita.hora}.'
        ),
        cita=cita,
        url=reverse(f'calendario_{cita.convenio}'),
    )


def _notificar_cita_rechazada(cita):
    """El radiólogo rechazó la solicitud: se avisa a quien la creó."""
    Notificacion.notificar(
        destinatario=cita.creada_por,
        tipo=Notificacion.TIPO_CITA_RECHAZADA,
        mensaje=(
            f'Cita rechazada: {cita.tipo_estudio} de {cita.paciente.nombre} '
            f'{cita.paciente.apellido}. Motivo: {cita.motivo_rechazo or "—"}'
        ),
        cita=cita,
        url=reverse(f'calendario_{cita.convenio}'),
    )


def _notificar_orden_pendiente(cita):
    """Aviso para el equipo de técnicos: hay una orden de trabajo nueva
    esperando que le tomen las imágenes."""
    tecnicos = Usuario.objects.filter(rol=Usuario.ROL_TECNICO_IMAGENES, is_active=True)
    Notificacion.notificar_a_varios(
        usuarios=tecnicos,
        tipo=Notificacion.TIPO_ORDEN_PENDIENTE,
        mensaje=(
            f'Nueva orden de trabajo: {cita.tipo_estudio} para {cita.paciente.nombre} '
            f'{cita.paciente.apellido}.'
        ),
        cita=cita,
        url=reverse('ordenes_pendientes'),
    )


def _url_recepcion_para(cita, usuario):
    """A dónde lleva el aviso de "estudio verificado": Caja va al cobro; el
    resto de recepción, a la pantalla de trabajo del convenio."""
    if es_caja(usuario):
        return reverse('pagos_pendientes')
    if cita.convenio in (Cita.CONVENIO_COEX, Cita.CONVENIO_PRIVADO):
        return f'{reverse(f"procesar_citas_{cita.convenio}")}?fecha={cita.fecha}'
    return reverse('pantalla_turnos')


def _notificar_estudio_validado(cita):
    """El técnico confirmó que el estudio es el correcto: recepción y Caja
    ya pueden cobrarlo."""
    usuarios = Usuario.objects.filter(is_active=True).filter(
        Q(rol=Usuario.ROL_RECEPCIONISTA) | Q(puede_operar_caja=True)
    ).distinct()
    mensaje = (
        f'Estudio verificado por el técnico: {cita.tipo_estudio} de {cita.paciente.nombre} '
        f'{cita.paciente.apellido}. Ya se puede cobrar.'
    )
    for usuario in usuarios:
        Notificacion.notificar(
            destinatario=usuario, tipo=Notificacion.TIPO_ESTUDIO_VALIDADO,
            mensaje=mensaje, cita=cita, url=_url_recepcion_para(cita, usuario),
        )


def _notificar_modificacion_solicitada(cita, nota):
    """El técnico encontró un error en el estudio: se le avisa a recepción
    qué hay que cambiar."""
    recepcionistas = Usuario.objects.filter(rol=Usuario.ROL_RECEPCIONISTA, is_active=True)
    mensaje = (
        f'Modificar estudio de {cita.paciente.nombre} {cita.paciente.apellido} '
        f'({cita.tipo_estudio}): {nota}'
    )
    Notificacion.notificar_a_varios(
        usuarios=recepcionistas,
        tipo=Notificacion.TIPO_MODIFICACION_SOLICITADA,
        mensaje=mensaje[:255],
        cita=cita,
        url=reverse('corregir_estudio_cita', args=[cita.id]),
    )


def _notificar_estudio_actualizado(orden):
    """Recepción hizo el cambio pedido: el técnico tiene que confirmar que
    ahora sí es el estudio correcto."""
    cita = orden.cita
    tecnicos = Usuario.objects.filter(rol=Usuario.ROL_TECNICO_IMAGENES, is_active=True)
    Notificacion.notificar_a_varios(
        usuarios=tecnicos,
        tipo=Notificacion.TIPO_ESTUDIO_ACTUALIZADO,
        mensaje=(
            f'Estudio actualizado por recepción: {cita.tipo_estudio} de {cita.paciente.nombre} '
            f'{cita.paciente.apellido}. Revisalo y confirmá "Estudio correcto".'
        )[:255],
        cita=cita,
        url=reverse('adjuntar_imagenes', args=[orden.id]),
    )


def _notificar_estudio_listo_para_informar(cita):
    """Cuando el técnico termina de subir las imágenes, se avisa al
    radiólogo asignado (o a todo el equipo de radiología si la cita no
    tenía uno asignado, como los tickets de emergencia)."""
    if cita.radiologo_id:
        radiologos = [cita.radiologo]
    else:
        radiologos = Usuario.objects.filter(rol=Usuario.ROL_MEDICO_RADIOLOGO, is_active=True)
    Notificacion.notificar_a_varios(
        usuarios=radiologos,
        tipo=Notificacion.TIPO_ESTUDIO_LISTO_INFORMAR,
        mensaje=(
            f'Estudio listo para informar: {cita.tipo_estudio} de {cita.paciente.nombre} '
            f'{cita.paciente.apellido}.'
        ),
        cita=cita,
        url=reverse('citas_procesadas'),
    )


def _notificar_estudio_completado(cita):
    """Cuando el radiólogo termina el informe (diagnóstico), se avisa a
    todo el equipo de recepción para que puedan entregar el resultado."""
    try:
        url = reverse(f'procesar_citas_{cita.convenio}')
    except NoReverseMatch:
        # Todavía no existe una pantalla de "procesar citas" para este
        # convenio (por ahora solo COEX la tiene); igual se notifica, solo
        # que el enlace de la notificación cae al panel principal.
        url = reverse('dashboard')
    recepcionistas = Usuario.objects.filter(rol=Usuario.ROL_RECEPCIONISTA, is_active=True)
    Notificacion.notificar_a_varios(
        usuarios=recepcionistas,
        tipo=Notificacion.TIPO_ESTUDIO_COMPLETADO,
        mensaje=(
            f'Estudio completado: {cita.tipo_estudio} de {cita.paciente.nombre} {cita.paciente.apellido}. '
            'Informe y diagnóstico listos.'
        ),
        cita=cita,
        url=url,
    )


def _notificar_reporte_enviado(reporte, enviado_por):
    """Cuando la recepcionista envía el reporte diario, se avisa a todo el
    equipo de administración financiera para que puedan revisarlo."""
    destinatarios = Usuario.objects.filter(rol=Usuario.ROL_ADMINISTRADOR_FINANCIERO, is_active=True)
    Notificacion.notificar_a_varios(
        usuarios=destinatarios,
        tipo=Notificacion.TIPO_REPORTE_ENVIADO,
        mensaje=(
            f'Nuevo reporte diario enviado: {reporte.get_convenio_display()} del {reporte.fecha}, '
            f'por {enviado_por.get_full_name() or enviado_por.username}.'
        ),
        url=reverse('ver_reporte_diario', args=[reporte.convenio, reporte.fecha.strftime("%Y-%m-%d")]),
    )


CAMPOS_DATOS_PACIENTE = ('nombre', 'apellido', 'sexo', 'telefono', 'correo', 'fecha_nacimiento')
# Datos de contacto que SÍ se pueden corregir al agendar una cita de un
# paciente ya registrado (el resto solo se completa si estaba vacío).
CAMPOS_CONTACTO_EDITABLES = ('telefono', 'correo')


def obtener_o_actualizar_paciente(cd):
    """Reutiliza el paciente si el DPI ya existe (evita duplicar el registro).

    Para un paciente que YA está registrado, la pantalla de agendar completa
    los datos que estén vacíos (nombre, apellido, sexo, fecha de nacimiento,
    carné IGSS) y además permite CORREGIR el teléfono y el correo
    (`CAMPOS_CONTACTO_EDITABLES`), porque son los que más cambian. El resto de
    correcciones se hacen desde "Completar datos del paciente" o el admin."""
    carnet_igss = cd.get('carnet_igss') or None
    paciente, creado = Paciente.objects.get_or_create(
        dpi=cd['dpi'],
        defaults={**{campo: cd[campo] for campo in CAMPOS_DATOS_PACIENTE}, 'carnet_igss': carnet_igss},
    )
    if not creado:
        cambiados = []
        for campo in CAMPOS_DATOS_PACIENTE:
            valor_nuevo = cd[campo]
            if campo in CAMPOS_CONTACTO_EDITABLES:
                # Teléfono y correo: se actualizan si viene un valor distinto.
                if valor_nuevo and valor_nuevo != getattr(paciente, campo):
                    setattr(paciente, campo, valor_nuevo)
                    cambiados.append(campo)
            elif valor_nuevo and not getattr(paciente, campo):
                # El resto solo se rellena si el paciente NO tiene ese dato.
                setattr(paciente, campo, valor_nuevo)
                cambiados.append(campo)
        if carnet_igss and not paciente.carnet_igss:
            paciente.carnet_igss = carnet_igss
            cambiados.append('carnet_igss')
        if cambiados:
            paciente.save(update_fields=cambiados)
    _notificar_datos_pendientes_si_corresponde(paciente)
    return paciente


def _notificar_datos_pendientes_si_corresponde(paciente):
    """Si el paciente quedó con datos opcionales sin llenar (teléfono o
    fecha de nacimiento), avisa a las recepcionistas activas. No duplica
    el aviso si ya hay uno sin leer para este mismo paciente — por eso se
    puede llamar cada vez que se agenda una cita o se registra un ticket
    sin que se acumulen notificaciones repetidas."""
    campos = paciente.campos_pendientes()
    if not campos:
        return
    url = reverse('completar_datos_paciente', args=[paciente.id])
    ya_avisado = Notificacion.objects.filter(
        tipo=Notificacion.TIPO_DATOS_PACIENTE_PENDIENTES, url=url, leida=False,
    ).exists()
    if ya_avisado:
        return
    recepcionistas = Usuario.objects.filter(rol=Usuario.ROL_RECEPCIONISTA, is_active=True)
    Notificacion.notificar_a_varios(
        usuarios=recepcionistas,
        tipo=Notificacion.TIPO_DATOS_PACIENTE_PENDIENTES,
        mensaje=(
            f'{paciente.nombre} {paciente.apellido} (DPI {paciente.dpi}) tiene datos '
            f'pendientes: {", ".join(campos)}.'
        ),
        url=url,
    )


@login_required
@user_passes_test(es_recepcionista)
def completar_datos_paciente(request, paciente_id):
    """Pantalla a la que llega la recepcionista al hacer clic en la
    notificación de "datos pendientes": deja llenar teléfono y/o fecha de
    nacimiento sin tener que pasar de nuevo por agendar una cita."""
    paciente = get_object_or_404(Paciente, id=paciente_id)

    if request.method == 'POST':
        form = CompletarDatosPacienteForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            cambiados = [
                campo for campo in ('telefono', 'fecha_nacimiento')
                if cd[campo] and getattr(paciente, campo) != cd[campo]
            ]
            for campo in cambiados:
                setattr(paciente, campo, cd[campo])
            if cambiados:
                paciente.save(update_fields=cambiados)
                messages.success(
                    request, f'Datos de {paciente.nombre} {paciente.apellido} actualizados.'
                )
            else:
                messages.info(request, 'No se cargó ningún dato nuevo.')

            if paciente.campos_pendientes():
                return redirect('completar_datos_paciente', paciente_id=paciente.id)

            # Recién ahora quedó completo: recién ahora se apaga el aviso
            # (para cualquier recepcionista, no solo quien lo llenó). Hasta
            # este punto la notificación se queda, aunque ya se haya
            # abierto/leído esta pantalla.
            Notificacion.objects.filter(
                tipo=Notificacion.TIPO_DATOS_PACIENTE_PENDIENTES,
                url=reverse('completar_datos_paciente', args=[paciente.id]),
                leida=False,
            ).update(leida=True)
            return redirect('dashboard')
    else:
        form = CompletarDatosPacienteForm(initial={
            'telefono': paciente.telefono,
            'fecha_nacimiento': paciente.fecha_nacimiento,
        })

    return render(request, 'pacientes/completar_datos_paciente.html', {
        'form': form,
        'paciente': paciente,
        'pendientes': paciente.campos_pendientes(),
    })


@login_required
@user_passes_test(es_recepcionista)
def buscar_paciente_por_dpi(request):
    """Usado por el formulario de agendar cita / registrar ticket para
    autocompletar los datos si el paciente ya está registrado, en vez de
    hacer que el recepcionista los vuelva a escribir."""
    dpi = (request.GET.get('dpi') or '').strip()
    paciente = Paciente.objects.filter(dpi=dpi).first() if dpi else None
    if not paciente:
        return JsonResponse({'encontrado': False})
    return JsonResponse({
        'encontrado': True,
        'nombre': paciente.nombre,
        'apellido': paciente.apellido,
        'sexo': paciente.sexo,
        'telefono': paciente.telefono,
        'correo': paciente.correo or '',
        'fecha_nacimiento': (
            paciente.fecha_nacimiento.isoformat() if paciente.fecha_nacimiento else ''
        ),
        'carnet_igss': paciente.carnet_igss or '',
    })


@login_required
@user_passes_test(es_recepcionista)
def radiologos_por_estudio(request):
    """Usado por el formulario de agendar cita: al elegir el tipo de
    estudio, solo deja elegir entre los radiólogos que realmente lo
    realizan (ej. Celeste solo hace Ultrasonido y Rayos X)."""
    tipo_estudio_id = request.GET.get('tipo_estudio')
    radiologos = Usuario.objects.filter(
        rol=Usuario.ROL_MEDICO_RADIOLOGO, is_active=True, tipos_estudio_asignados__id=tipo_estudio_id,
    ).order_by('username').distinct()
    return JsonResponse({
        'radiologos': [
            {'id': r.id, 'texto': r.get_full_name() or r.username} for r in radiologos
        ],
    })


@login_required
@user_passes_test(es_recepcionista)
def historial_pacientes(request):
    """Listado de pacientes con al menos un estudio ya realizado (informe
    entregado), con búsqueda por nombre/apellido, DPI o N° de expediente y
    filtros por convenio, fecha y tipo de estudio. Los que todavía tienen datos
    pendientes (sexo/teléfono/fecha de nacimiento) van primero, con un
    botón para completarlos; a los demás se les muestra de qué
    convenio(s) son sus estudios (COEX, Privado, Emergencia IGSS)."""
    busqueda = (request.GET.get('q') or '').strip()
    filtro_convenio = (request.GET.get('convenio') or '').strip()
    filtro_fecha = (request.GET.get('fecha') or '').strip()
    filtro_tipo_estudio = (request.GET.get('tipo_estudio') or '').strip()
    filtro_estado_pago = (request.GET.get('estado_pago') or '').strip()
    filtro_agrupacion = (request.GET.get('agrupacion') or '').strip()

    citas_procesadas = Cita.objects.filter(estado=Cita.ESTADO_PROCESADA)
    if filtro_convenio:
        citas_procesadas = citas_procesadas.filter(convenio=filtro_convenio)
    if filtro_fecha:
        citas_procesadas = citas_procesadas.filter(fecha=filtro_fecha)
    if filtro_tipo_estudio:
        citas_procesadas = citas_procesadas.filter(tipo_estudio_id=filtro_tipo_estudio)
    if filtro_estado_pago == 'pagado':
        citas_procesadas = citas_procesadas.filter(cobro__estado=Cobro.ESTADO_PAGADO)
    elif filtro_estado_pago == 'pendiente':
        citas_procesadas = citas_procesadas.filter(
            Q(cobro__estado=Cobro.ESTADO_PENDIENTE)
            | Q(detalles_orden_pago__orden_pago__estado=OrdenPago.ESTADO_PENDIENTE)
        ).distinct()
    if filtro_agrupacion == 'agrupado':
        citas_procesadas = citas_procesadas.filter(
            detalles_orden_pago__orden_pago__isnull=False,
        ).distinct()
    elif filtro_agrupacion == 'individual':
        citas_procesadas = citas_procesadas.filter(
            detalles_orden_pago__isnull=True,
        )

    pacientes_qs = Paciente.objects.filter(
        id__in=citas_procesadas.values('paciente_id')
    ).distinct()
    if busqueda:
        pacientes_qs = pacientes_qs.filter(
            Q(nombre__icontains=busqueda)
            | Q(apellido__icontains=busqueda)
            | Q(dpi__icontains=busqueda)
            | Q(expediente__icontains=busqueda)
        )

    pacientes = list(pacientes_qs)

    convenios_por_paciente = {}
    if pacientes:
        convenios_choices = dict(Cita.CONVENIO_CHOICES)
        # .order_by() (sin argumentos) es necesario: si no, el `ordering`
        # por defecto de Cita (fecha, hora) se cuela en el SELECT y hace
        # que .distinct() no junte filas de un mismo convenio con distinta
        # fecha, mostrando el mismo convenio repetido para un paciente.
        filas = (
            Cita.objects.filter(paciente__in=pacientes, estado=Cita.ESTADO_PROCESADA)
            .order_by().values_list('paciente_id', 'convenio').distinct()
        )
        for paciente_id, convenio in filas:
            convenios_por_paciente.setdefault(paciente_id, []).append(
                convenios_choices.get(convenio, convenio)
            )

    for paciente in pacientes:
        paciente.datos_pendientes = paciente.campos_pendientes()
        paciente.convenios_estudios = sorted(convenios_por_paciente.get(paciente.id, []))

    # Los que tienen datos pendientes primero, para que salten a la vista;
    # el resto en orden alfabético, como antes.
    pacientes.sort(key=lambda p: (not p.datos_pendientes, p.nombre, p.apellido))

    contexto = {
        'pacientes': pacientes,
        'busqueda': busqueda,
        'filtro_convenio': filtro_convenio,
        'filtro_fecha': filtro_fecha,
        'filtro_tipo_estudio': filtro_tipo_estudio,
        'filtro_estado_pago': filtro_estado_pago,
        'filtro_agrupacion': filtro_agrupacion,
        'tipos_estudio': TipoEstudio.objects.filter(
            id__in=Cita.objects.filter(estado=Cita.ESTADO_PROCESADA).values('tipo_estudio_id')
        ).order_by('nombre'),
    }

    # Búsqueda en vivo: el JS de la página pide solo el listado (sin el
    # HTML completo) a medida que se escribe en el buscador.
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'pacientes/includes/_resultados_pacientes.html', contexto)

    return render(request, 'pacientes/historial_pacientes.html', contexto)


@login_required
@user_passes_test(es_recepcionista)
def historial_paciente(request, paciente_id):
    """Estudios ya realizados (con informe) de un paciente, del más
    reciente al más antiguo."""
    paciente = get_object_or_404(Paciente, id=paciente_id)
    filtro_estado_pago = (request.GET.get('estado_pago') or '').strip()
    filtro_agrupacion = (request.GET.get('agrupacion') or '').strip()
    citas = (
        Cita.objects.filter(paciente=paciente, estado=Cita.ESTADO_PROCESADA)
        .select_related('tipo_estudio', 'orden_trabajo', 'cobro')
        .prefetch_related('detalles_orden_pago__orden_pago__combo')
        .order_by('-fecha', '-hora')
    )
    if filtro_estado_pago == 'pagado':
        citas = citas.filter(cobro__estado=Cobro.ESTADO_PAGADO)
    elif filtro_estado_pago == 'pendiente':
        citas = citas.filter(
            Q(cobro__estado=Cobro.ESTADO_PENDIENTE)
            | Q(detalles_orden_pago__orden_pago__estado=OrdenPago.ESTADO_PENDIENTE)
        ).distinct()
    if filtro_agrupacion == 'agrupado':
        citas = citas.filter(detalles_orden_pago__orden_pago__isnull=False).distinct()
    elif filtro_agrupacion == 'individual':
        citas = citas.filter(detalles_orden_pago__isnull=True)
    citas = list(citas)
    for cita in citas:
        cita.ordenes_agrupadas = [
            detalle.orden_pago for detalle in cita.detalles_orden_pago.all()
        ]
    # Para llenar el combo de "Estudio" del filtro solo con los tipos que
    # este paciente realmente tiene (no el catálogo completo).
    tipos_estudio = sorted({cita.tipo_estudio.nombre for cita in citas})
    return render(request, 'pacientes/historial_paciente.html', {
        'paciente': paciente,
        'citas': citas,
        'tipos_estudio': tipos_estudio,
        'filtro_estado_pago': filtro_estado_pago,
        'filtro_agrupacion': filtro_agrupacion,
        'edad': paciente.edad_en(timezone.localdate()),
        'hoy': timezone.localdate(),
    })


def _cobro_bloquea_envio(cita):
    """True si la cita tiene un cobro registrado que sigue pendiente: en ese
    caso no se permite enviar los resultados hasta que se marque como
    cobrado desde Caja. Si no hay cobro (todavía no se generó orden, o la
    orden es de antes de este permiso), no bloquea — el cobro no es
    obligatorio. Portado (2026-09-04) desde la rama visual-andres de
    TechBlood."""
    if OrdenPago.objects.filter(
        detalles__cita=cita,
        estado__in=(OrdenPago.ESTADO_PENDIENTE,),
    ).exists():
        return True
    return bool(
        hasattr(cita, 'cobro') and cita.cobro and cita.cobro.estado != Cobro.ESTADO_PAGADO
    )


def _enviar_estudio_y_registrar(request, cita, orden):
    """Envía el estudio (asume que el paciente ya tiene correo) y deja
    constancia: bitácora, marca de tiempo y mensaje de éxito. Si el envío
    falla, avisa con el motivo concreto (ver enviar_resultados) en vez de
    dejar la pantalla reventar, y NO marca el estudio como enviado — así el
    botón sigue disponible para reintentar. Si el estudio tiene un cobro
    pendiente, no se envía."""
    if _cobro_bloquea_envio(cita):
        messages.error(
            request,
            f'El estudio de {cita.paciente} tiene un cobro pendiente. '
            'Primero marcá el cobro como realizado desde Caja para poder enviar los resultados.',
        )
        return

    error = enviar_resultados(orden)
    if error:
        messages.error(
            request,
            f'No se pudo enviar el estudio a {cita.paciente}: {error}. '
            'El estudio sigue marcado como no enviado, podés reintentar.',
        )
        return

    orden.resultados_enviados_en = timezone.now()
    orden.save(update_fields=['resultados_enviados_en'])

    Bitacora.registrar(
        request=request,
        usuario=request.user,
        accion=Bitacora.ACCION_ENVIAR_ESTUDIO,
        descripcion=f'Envió el estudio de {cita.paciente} (cita #{cita.id}) por correo.',
    )
    messages.success(request, f'Estudio enviado a {cita.paciente} ({cita.paciente.correo}).')


@login_required
@user_passes_test(es_recepcionista)
@require_POST
def enviar_estudio(request, cita_id):
    """Envía los resultados del estudio al correo del paciente. Antes esto
    pasaba automático cuando la radióloga adjuntaba el informe; ahora lo
    dispara la recepcionista a mano desde "Estudios realizados", una vez
    que quiere confirmar el envío (botón "Enviar estudio"). Si el paciente
    todavía no tiene correo registrado, primero la manda a completarlo."""
    cita = get_object_or_404(Cita, id=cita_id, estado=Cita.ESTADO_PROCESADA)
    orden = OrdenTrabajo.objects.filter(cita=cita).first()
    if not orden:
        messages.error(
            request,
            'Este estudio no tiene una orden de trabajo. No se puede enviar hasta que '
            'Técnico y Radiología completen el flujo.',
        )
        return redirect('historial_paciente', paciente_id=cita.paciente_id)

    if not cita.paciente.correo:
        return redirect('ingresar_correo_envio', cita_id=cita.id)

    _enviar_estudio_y_registrar(request, cita, orden)
    return redirect('historial_paciente', paciente_id=cita.paciente_id)


@login_required
@user_passes_test(es_recepcionista)
def ingresar_correo_envio(request, cita_id):
    """El paciente no tenía correo registrado al momento de enviar el
    estudio: pide el correo acá y, al guardarlo, envía el estudio de una
    vez (sin que la recepcionista tenga que volver a apretar "Enviar
    estudio")."""
    cita = get_object_or_404(Cita, id=cita_id, estado=Cita.ESTADO_PROCESADA)
    orden = get_object_or_404(OrdenTrabajo, cita=cita)

    if cita.paciente.correo:
        # Ya se completó (ej. en otra pestaña); no hace falta este paso,
        # se envía directo.
        _enviar_estudio_y_registrar(request, cita, orden)
        return redirect('historial_paciente', paciente_id=cita.paciente_id)

    if request.method == 'POST':
        form = IngresarCorreoEnvioForm(request.POST)
        if form.is_valid():
            paciente = cita.paciente
            paciente.correo = form.cleaned_data['correo']
            paciente.save(update_fields=['correo'])
            _enviar_estudio_y_registrar(request, cita, orden)
            return redirect('historial_paciente', paciente_id=cita.paciente_id)
    else:
        form = IngresarCorreoEnvioForm()

    if request.method == 'POST':
        avisar_si_correo_no_existe(request, form)

    return render(request, 'pacientes/ingresar_correo_envio.html', {
        'form': form,
        'cita': cita,
    })


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
    """Acceso directo a Caja ya filtrado por Emergencia IGSS, para el botón
    "Pagos IGSS" del panel (ver accounts.pantallas)."""
    return redirect(f"{reverse('pagos_pendientes')}?convenio={Cita.CONVENIO_EMERGENCIA_IGSS}")


@login_required
@user_passes_test(es_caja)
def pagos_pendientes(request):
    """Listado paginado de cobros, con filtros para Caja."""
    qs = Cobro.objects.select_related(
        'cita__paciente', 'cita__tipo_estudio', 'cita__orden_trabajo', 'cobrado_por',
    ).order_by('-creado_en')
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

    # Solo entran a una orden agrupada los estudios que el técnico ya
    # confirmó como correctos (ver OrdenTrabajo.validacion_estado). Se arma
    # aparte de `qs` (no filtrando sobre ella) para que siempre traiga TODOS
    # los pendientes de COEX y Emergencia IGSS sin importar qué convenio
    # haya elegido la recepcionista en el filtro de la pantalla -- el
    # formulario para crearla solo se muestra en Pagos IGSS (ver template),
    # pero agrupa estudios de ambos convenios.
    cobros_para_orden = Cobro.objects.filter(
        estado=Cobro.ESTADO_PENDIENTE,
        cita__convenio__in=(Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS),
        cita__orden_trabajo__validacion_estado=OrdenTrabajo.VALIDACION_CORRECTO,
    ).select_related('cita__paciente', 'cita__tipo_estudio').order_by('-creado_en')
    pagina = Paginator(qs, 20).get_page(request.GET.get('page'))

    filtros = request.GET.copy()
    filtros.pop('page', None)
    ordenes_pago = OrdenPago.objects.select_related(
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
        'combos_preview': [
            {
                'id': combo.id,
                'nombre': combo.nombre,
                'porcentaje': float(combo.porcentaje_descuento or 0),
                'estudios': list(combo.estudios.values_list('id', flat=True)),
            }
            for combo in combos
        ],
    })


@login_required
@user_passes_test(es_caja)
@require_POST
def crear_orden_pago(request):
    """Agrupa estudios pendientes de un mismo paciente y convenio COEX/IGSS."""
    cita_ids = request.POST.getlist('cita_ids')
    if not cita_ids:
        messages.error(request, 'Seleccione al menos un estudio para crear la orden de pago.')
        return redirect('pagos_pendientes')

    form = CrearOrdenPagoForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Revise el combo seleccionado y las notas de la orden.')
        return redirect('pagos_pendientes')

    with transaction.atomic():
        citas = list(
            Cita.objects.select_for_update().select_related('paciente', 'tipo_estudio')
            .prefetch_related('estudios_extra')
            .filter(
                id__in=cita_ids,
                convenio__in=(Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS),
                orden_trabajo__isnull=False,
            )
        )
        if len(citas) != len(set(cita_ids)):
            messages.error(request, 'Uno o más estudios seleccionados no son válidos para una orden agrupada.')
            return redirect('pagos_pendientes')
        claves = {(c.paciente_id, c.convenio) for c in citas}
        if len(claves) != 1:
            messages.error(request, 'La orden debe contener estudios del mismo paciente y convenio.')
            return redirect('pagos_pendientes')
        if any(
            not hasattr(c, 'cobro') or c.cobro.estado != Cobro.ESTADO_PENDIENTE
            or OrdenPago.objects.filter(detalles__cita=c, estado=OrdenPago.ESTADO_PENDIENTE).exists()
            for c in citas
        ):
            messages.error(request, 'Solo se pueden agrupar estudios con cobro pendiente y sin otra orden abierta.')
            return redirect('pagos_pendientes')
        if any(not c.cobro.listo_para_cobrar for c in citas):
            messages.error(
                request,
                'Solo se pueden agrupar estudios que el técnico ya confirmó como correctos.',
            )
            return redirect('pagos_pendientes')

        combo = form.cleaned_data['combo']
        detalles = []
        subtotal = Decimal('0.00')
        tipos = set()
        for cita in citas:
            precio = cita.precio_base
            detalles.append((cita, cita.tipo_estudio, None, precio))
            subtotal += precio
            tipos.add(cita.tipo_estudio_id)
            for extra in cita.estudios_extra.all():
                precio_extra = extra.precio
                detalles.append((cita, extra.tipo_estudio, extra, precio_extra))
                subtotal += precio_extra
                tipos.add(extra.tipo_estudio_id)

        descuento = Decimal('0.00')
        if combo:
            combo_ids = set(combo.estudios.values_list('id', flat=True))
            if not combo_ids.issubset(tipos):
                messages.error(request, 'El combo elegido no coincide con todos los estudios seleccionados.')
                return redirect('pagos_pendientes')
            descuento = (subtotal * (combo.porcentaje_descuento or 0) / 100).quantize(Decimal('0.01'))
        elif tipos:
            combo = Combo.objects.filter(
                activo=True, estudios__id__in=tipos,
            ).prefetch_related('estudios').distinct().order_by('id').first()
            if combo:
                combo_ids = set(combo.estudios.values_list('id', flat=True))
                if combo_ids.issubset(tipos):
                    descuento = (
                        subtotal * (combo.porcentaje_descuento or 0) / 100
                    ).quantize(Decimal('0.01'))
                else:
                    combo = None

        orden = OrdenPago.objects.create(
            convenio=citas[0].convenio,
            paciente=citas[0].paciente,
            subtotal=subtotal,
            descuento=descuento,
            total=subtotal - descuento,
            combo=combo,
            notas=form.cleaned_data['notas'],
            creado_por=request.user,
        )
        descuento_unitario = (descuento / len(detalles)).quantize(Decimal('0.01')) if detalles else 0
        for cita, tipo, extra, precio in detalles:
            DetalleOrdenPago.objects.create(
                orden_pago=orden,
                cita=cita,
                tipo_estudio=tipo,
                estudio_extra=extra,
                precio=precio,
                descuento=descuento_unitario,
                total=precio - descuento_unitario,
            )

    messages.success(request, f'Orden de pago #{orden.id} creada y pendiente de boleta.')
    return redirect('pagos_pendientes')


@login_required
@user_passes_test(es_caja)
@require_POST
def pagar_orden_pago(request, orden_id):
    """Adjunta la boleta global y liquida todos los estudios de la orden."""
    orden = get_object_or_404(
        OrdenPago.objects.prefetch_related('detalles__cita'),
        id=orden_id,
        estado=OrdenPago.ESTADO_PENDIENTE,
    )
    form = RegistrarPagoEstudioForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'Adjunte una boleta válida y complete los datos del pago.')
        return redirect('pagos_pendientes')
    if not form.cleaned_data['comprobante_bancario']:
        messages.error(request, 'La orden agrupada requiere adjuntar la boleta global.')
        return redirect('pagos_pendientes')

    with transaction.atomic():
        orden.numero_boleta = form.cleaned_data['numero_boleta']
        orden.comprobante_bancario = form.cleaned_data['comprobante_bancario']
        orden.estado = OrdenPago.ESTADO_PAGADA
        orden.pagado_por = request.user
        orden.pagado_en = timezone.now()
        orden.save(update_fields=[
            'numero_boleta', 'comprobante_bancario', 'estado', 'pagado_por', 'pagado_en',
        ])
        for detalle in orden.detalles.select_related('cita'):
            cobro, _ = Cobro.objects.get_or_create(cita=detalle.cita)
            cobro.forma_pago = form.cleaned_data['forma_pago']
            cobro.numero_boleta = orden.numero_boleta
            cobro.comprobante_bancario = orden.comprobante_bancario.name
            cobro.marcar_pagado(request.user, notas=form.cleaned_data['notas'])

    messages.success(request, f'Orden de pago #{orden.id} confirmada y estudios liberados.')
    return redirect('pagos_pendientes')


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
        Cobro.objects.select_related('cita__paciente', 'cita__tipo_estudio', 'cobrado_por'),
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
    items_servicio += [(e.tipo_estudio.nombre, e.precio) for e in cita.estudios_extra.all()]

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
    cobro = get_object_or_404(
        Cobro.objects.select_related('cita'),
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
        Cobro.objects.select_related('cita__paciente', 'cita__tipo_estudio', 'cobrado_por'),
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
    cobro = get_object_or_404(
        Cobro.objects.select_related('cita'),
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
    cobro = get_object_or_404(Cobro, id=cobro_id, estado=Cobro.ESTADO_PAGADO)
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
        Cita.objects.filter(
            estado__in=(Cita.ESTADO_EN_PROCESO, Cita.ESTADO_PROCESADA),
            orden_trabajo__isnull=False,
        ),
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
    return redirect('pagos_pendientes')


@login_required
@user_passes_test(es_recepcionista)
def ver_estudio_historial(request, cita_id):
    """Vista de solo lectura de un estudio ya realizado: imágenes e
    informe, tal como quedaron al terminar el proceso."""
    cita = get_object_or_404(Cita, id=cita_id, estado=Cita.ESTADO_PROCESADA)
    orden = get_object_or_404(OrdenTrabajo, cita=cita)
    # Se excluyen las imágenes sin archivo cargado: acceder a `.url` de un
    # FileField vacío revienta el render de la plantilla.
    imagenes = orden.imagenes.exclude(archivo='').order_by('subida_en')
    return render(request, 'pacientes/ver_estudio_historial.html', {
        'cita': cita,
        'orden': orden,
        'imagenes': imagenes,
        'informes': orden.informes.select_related('tipo_estudio').all(),
        'edad': orden.edad_paciente,
        'volver_url': reverse('historial_paciente', args=[cita.paciente_id]),
    })


@login_required
@user_passes_test(es_administrador)
def crear_estudio(request):
    if request.method == 'POST':
        form = CrearTipoEstudioForm(request.POST)
        if form.is_valid():
            tipo_estudio = form.save()
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_CREAR_ESTUDIO,
                descripcion=(
                    f'Creó el estudio "{tipo_estudio.nombre}" '
                    f'({tipo_estudio.get_modalidad_display()}, {tipo_estudio.duracion_minutos} min).'
                ),
            )
            messages.success(request, f'Estudio "{tipo_estudio.nombre}" creado correctamente.')
            return redirect('dashboard')
    else:
        form = CrearTipoEstudioForm()
    return render(request, 'pacientes/crear_estudio.html', {'form': form, 'editando': None})

@login_required
@user_passes_test(es_administrador)
def lista_modalidades(request):
    busqueda = (request.GET.get('q') or '').strip()

    modalidades = Modalidad.objects.all().order_by('nombre')

    if busqueda:
        modalidades = modalidades.filter(nombre__icontains=busqueda)

    return render(request, 'pacientes/lista_modalidades.html', {
        'modalidades': modalidades,
        'busqueda': busqueda,
    })

@login_required
@user_passes_test(es_administrador)
def crear_modalidad(request):
    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()

        if not nombre:
            messages.error(request, 'Escriba el nombre de la modalidad.')
        elif Modalidad.objects.filter(nombre__iexact=nombre).exists():
            messages.error(request, 'Ya existe una modalidad con ese nombre.')
        else:
            base_codigo = slugify(nombre).replace('-', '_')[:30] or 'modalidad'
            codigo = base_codigo
            contador = 2

            while Modalidad.objects.filter(codigo=codigo).exists():
                sufijo = f'_{contador}'
                codigo = f'{base_codigo[:30-len(sufijo)]}{sufijo}'
                contador += 1

            modalidad = Modalidad.objects.create(
                nombre=nombre,
                codigo=codigo
)

            HistorialModalidad.objects.create(
                modalidad=modalidad,
                nombre=modalidad.nombre,
                nombre_anterior='',
                accion=HistorialModalidad.ACCION_CREAR,
                realizado_por=request.user,
            )

            messages.success(
                request,
                f'Modalidad "{modalidad.nombre}" creada correctamente.'
            )
            return redirect('lista_modalidades')

    return render(request, 'pacientes/crear_modalidad.html', {
        'editando': None,
    })

@login_required
@user_passes_test(es_administrador)
def editar_modalidad(request, modalidad_id):
    modalidad = get_object_or_404(Modalidad, id=modalidad_id)

    if request.method == 'POST':
        nombre_nuevo = (request.POST.get('nombre') or '').strip()

        if not nombre_nuevo:
            messages.error(request, 'Escriba el nombre de la modalidad.')

        elif (
            Modalidad.objects
            .filter(nombre__iexact=nombre_nuevo)
            .exclude(id=modalidad.id)
            .exists()
        ):
            messages.error(request, 'Ya existe otra modalidad con ese nombre.')

        elif nombre_nuevo != modalidad.nombre:
            nombre_anterior = modalidad.nombre

            modalidad.nombre = nombre_nuevo
            modalidad.save(update_fields=['nombre', 'actualizado_en'])

            HistorialModalidad.objects.create(
                modalidad=modalidad,
                nombre=modalidad.nombre,
                nombre_anterior=nombre_anterior,
                accion=HistorialModalidad.ACCION_EDITAR,
                realizado_por=request.user,
            )

            messages.success(
                request,
                f'Modalidad "{modalidad.nombre}" actualizada correctamente.'
            )
            return redirect('lista_modalidades')

        else:
            messages.info(request, 'No se realizaron cambios.')
            return redirect('lista_modalidades')

    return render(request, 'pacientes/crear_modalidad.html', {
        'editando': modalidad,
        'modalidad': modalidad,
    })


@login_required
@user_passes_test(es_administrador)
@require_POST
def eliminar_modalidad(request, modalidad_id):
    modalidad = get_object_or_404(Modalidad, id=modalidad_id)
    nombre = modalidad.nombre

    HistorialModalidad.objects.create(
        modalidad=modalidad,
        nombre=nombre,
        nombre_anterior=nombre,
        accion=HistorialModalidad.ACCION_ELIMINAR,
        realizado_por=request.user,
    )

    modalidad.activo = False
    modalidad.save(update_fields=['activo', 'actualizado_en'])

    messages.success(
        request,
        f'Modalidad "{nombre}" desactivada correctamente.'
    )

    return redirect('lista_modalidades')

@login_required
@user_passes_test(es_administrador)
@require_POST
def activar_modalidad(request, modalidad_id):
    modalidad = get_object_or_404(Modalidad, id=modalidad_id)

    modalidad.activo = True
    modalidad.save(update_fields=['activo', 'actualizado_en'])

    messages.success(
        request,
        f'Modalidad "{modalidad.nombre}" activada correctamente.'
    )

    return redirect('lista_modalidades')

@login_required
@user_passes_test(es_administrador)
def historial_modalidades(request):
    busqueda = (request.GET.get('q') or '').strip()

    registros = (
        HistorialModalidad.objects
        .select_related('realizado_por')
        .order_by('-creado_en')
    )

    if busqueda:
        registros = registros.filter(
            Q(nombre__icontains=busqueda)
            | Q(nombre_anterior__icontains=busqueda)
        )

    pagina = Paginator(registros, 25).get_page(request.GET.get('page'))

    return render(request, 'pacientes/historial_modalidades.html', {
        'pagina': pagina,
        'registros': pagina,
        'busqueda': busqueda,
    })


ESTUDIOS_POR_PAGINA = 20




@login_required
@user_passes_test(es_administrador)
def lista_estudios(request):
    busqueda = (request.GET.get('q') or '').strip()
    modalidad = (request.GET.get('modalidad') or '').strip()

    estudios = TipoEstudio.objects.all().prefetch_related('precios').order_by('modalidad', 'nombre')
    if busqueda:
        estudios = estudios.filter(nombre__icontains=busqueda)
    if modalidad in dict(TipoEstudio.MODALIDAD_CHOICES):
        estudios = estudios.filter(modalidad=modalidad)

    pagina = Paginator(estudios, ESTUDIOS_POR_PAGINA).get_page(request.GET.get('page'))

    filtros = request.GET.copy()
    filtros.pop('page', None)
    return render(request, 'pacientes/lista_estudios.html', {
        'estudios': pagina,
        'pagina': pagina,
        'busqueda': busqueda,
        'modalidad': modalidad,
        'modalidades': TipoEstudio.MODALIDAD_CHOICES,
        'filtros_qs': filtros.urlencode(),
    })


@login_required
@user_passes_test(es_administrador)
def editar_estudio(request, estudio_id):
    tipo_estudio = get_object_or_404(TipoEstudio, id=estudio_id)
    if request.method == 'POST':
        # Se lee ANTES de guardar: form.save() ya deja la matriz de precios
        # actualizada (ver CrearTipoEstudioForm.save), así que después no
        # hay forma de saber qué valor tenía cada celda.
        precios_antes = {
            (p.convenio, p.horario_habil): p.precio for p in tipo_estudio.precios.all()
        }
        form = CrearTipoEstudioForm(request.POST, instance=tipo_estudio)
        if form.is_valid():
            tipo_estudio = form.save()
            _auditar_cambios_precio(request, tipo_estudio, precios_antes)
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_EDITAR_ESTUDIO,
                descripcion=(
                    f'Editó el estudio "{tipo_estudio.nombre}" '
                    f'({tipo_estudio.get_modalidad_display()}, {tipo_estudio.duracion_minutos} min).'
                ),
            )
            messages.success(request, f'Estudio "{tipo_estudio.nombre}" actualizado correctamente.')
            return redirect('lista_estudios')
    else:
        form = CrearTipoEstudioForm(instance=tipo_estudio)
    return render(request, 'pacientes/crear_estudio.html', {
        'form': form,
        'editando': tipo_estudio,
        'historial_precios': tipo_estudio.historial_precios.select_related('modificado_por')[:10],
    })


def _auditar_cambios_precio(request, tipo_estudio, precios_antes):
    """Registra en HistorialPrecioEstudio + bitácora cada celda de la
    matriz de precios que cambió (mismo patrón que
    accounts.views._auditar_cambios_comision, para precios de estudio)."""
    cambiados = []
    precios_ahora = {(p.convenio, p.horario_habil): p.precio for p in tipo_estudio.precios.all()}
    for (convenio, habil), ahora in precios_ahora.items():
        antes = precios_antes.get((convenio, habil), Decimal('0.00'))
        if antes != ahora:
            HistorialPrecioEstudio.objects.create(
                tipo_estudio=tipo_estudio, convenio=convenio, horario_habil=habil,
                valor_anterior=antes, valor_nuevo=ahora,
                modificado_por=request.user,
            )
            cambiados.append((convenio, habil, antes, ahora))
    if cambiados:
        nombres_convenio = dict(Cita.CONVENIO_CHOICES)
        detalle = ', '.join(
            f'{nombres_convenio.get(c, c)} {"hábil" if h else "inhábil"}: Q{a} → Q{n}'
            for c, h, a, n in cambiados
        )
        Bitacora.registrar(
            request=request, usuario=request.user,
            accion=Bitacora.ACCION_EDITAR_PRECIO_ESTUDIO,
            descripcion=f'Cambió precios de "{tipo_estudio.nombre}": {detalle}',
        )


@login_required
@user_passes_test(es_administrador)
def historial_precios_estudio(request):
    """Auditoría de los cambios de precio de estudios: fecha, de cuánto a
    cuánto, y qué administrador lo hizo. Filtro por nombre del estudio."""
    busqueda = (request.GET.get('q') or '').strip()
    registros = (
        HistorialPrecioEstudio.objects.select_related('tipo_estudio', 'modificado_por')
        .order_by('-creado_en')
    )
    if busqueda:
        registros = registros.filter(tipo_estudio__nombre__icontains=busqueda)
    pagina = Paginator(registros, 25).get_page(request.GET.get('page'))
    return render(request, 'pacientes/historial_precios_estudio.html', {
        'pagina': pagina,
        'registros': pagina,
        'busqueda': busqueda,
    })


@login_required
@user_passes_test(es_administrador)
def lista_combos(request):
    """Catálogo de combos de estudios (ver pacientes.models.Combo): se
    administra íntegro desde acá, igual que Estudios (lista_estudios).
    Portado (2026-09-04) desde la rama visual-andres de TechBlood — ahí
    esta pantalla estaba abierta a cualquier recepcionista pero solo
    aparecía en el menú del administrador; se corrige ese permiso
    inconsistente al portarla."""
    combos = Combo.objects.all().prefetch_related('estudios').order_by('nombre')
    return render(request, 'pacientes/lista_combos.html', {'combos': combos})


def _avisar_si_combo_sin_radiologo_en_comun(request, combo, tipo_estudio):
    """El espejo del combo (ver Combo.sincronizar_tipo_estudio) solo queda
    con radiólogo para elegir al agendar si hay al menos uno que haga TODOS
    sus estudios. Si la intersección quedó vacía, se avisa -- el combo se
    crea/edita igual, solo que no se va a poder asignar radiólogo al
    agendarlo hasta que se corrija."""
    if combo.estudios.exists() and not tipo_estudio.radiologos.exists():
        messages.warning(
            request,
            f'Ningún radiólogo hace todos los estudios de "{combo.nombre}": no vas a poder '
            'asignarle uno al agendarlo. Revisá los radiólogos asignados a cada estudio '
            'del combo (Estudios) para que al menos uno cubra todos.',
        )


@login_required
@user_passes_test(es_administrador)
def crear_combo(request):
    if request.method == 'POST':
        form = ComboForm(request.POST)
        if form.is_valid():
            combo = form.save()
            tipo_estudio = combo.sincronizar_tipo_estudio()
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_CREAR_COMBO,
                descripcion=f'Creó el combo "{combo.nombre}" con {combo.estudios.count()} estudios.',
            )
            messages.success(request, f'Combo "{combo.nombre}" creado correctamente.')
            _avisar_si_combo_sin_radiologo_en_comun(request, combo, tipo_estudio)
            return redirect('lista_combos')
    else:
        form = ComboForm()
    return render(request, 'pacientes/crear_combo.html', {'form': form, 'editando': None})


@login_required
@user_passes_test(es_administrador)
def editar_combo(request, combo_id):
    combo = get_object_or_404(Combo, id=combo_id)
    if request.method == 'POST':
        form = ComboForm(request.POST, instance=combo)
        if form.is_valid():
            combo = form.save()
            tipo_estudio = combo.sincronizar_tipo_estudio()
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_EDITAR_COMBO,
                descripcion=f'Editó el combo "{combo.nombre}".',
            )
            messages.success(request, f'Combo "{combo.nombre}" actualizado correctamente.')
            _avisar_si_combo_sin_radiologo_en_comun(request, combo, tipo_estudio)
            return redirect('lista_combos')
    else:
        form = ComboForm(instance=combo)
    return render(request, 'pacientes/crear_combo.html', {'form': form, 'editando': combo})


@login_required
@user_passes_test(es_recepcionista)
def seleccionar_horario(request, convenio):
    convenio_nombre = dict(Cita.CONVENIO_CHOICES).get(convenio, convenio)

    reagendar_cita = None
    reagendar_id = request.GET.get('reagendar')
    if reagendar_id:
        reagendar_cita = get_object_or_404(Cita, id=reagendar_id, convenio=convenio)

    hoy = datetime.date.today()
    semana_param = parse_date(request.GET.get('semana', ''))
    inicio = inicio_semana(semana_param or hoy)
    dias = [inicio + datetime.timedelta(days=i) for i in range(len(DIAS_SEMANA))]

    citas_semana = (
        Cita.objects.filter(fecha__gte=dias[0], fecha__lte=dias[-1])
        .exclude(estado=Cita.ESTADO_RECHAZADA)
        .select_related('tipo_estudio', 'paciente', 'radiologo', 'orden_trabajo', 'cobro')
    )
    if reagendar_cita:
        citas_semana = citas_semana.exclude(id=reagendar_cita.id)

    # Selector de radiólogo: si se elige uno, el calendario muestra solo la
    # agenda de ESE radiólogo (para ver si tiene un hueco cuando otro está
    # lleno). Sin elegir, se ve la agenda de toda la clínica.
    radiologos = list(
        Usuario.objects.filter(rol=Usuario.ROL_MEDICO_RADIOLOGO, is_active=True)
        .order_by('first_name', 'last_name', 'username')
    )
    radiologo_id = request.GET.get('radiologo') or ''
    radiologo_seleccionado = next(
        (r for r in radiologos if str(r.id) == radiologo_id), None,
    )
    if radiologo_seleccionado:
        citas_semana = citas_semana.filter(radiologo=radiologo_seleccionado)

    # El calendario es único para toda la clínica: un turno ocupado por
    # cualquier convenio (COEX / Privado / Emergencia IGSS) se ve ocupado en
    # los tres. Se guarda además la lista de citas de cada franja para poder
    # mostrar (al hacer clic en un horario ocupado) a quién está asignada y
    # qué estudio es, y decidir si cabe una cita más.
    citas_por_dia = {}   # fecha -> [(rango, cita), ...]
    asignados_por_dia = {}  # fecha -> {hora: {etiquetas}}
    for cita in citas_semana:
        etiqueta = ETIQUETA_CONVENIO_CORTA.get(cita.convenio, cita.convenio)
        rango = rango_ocupado_por(cita.fecha, cita.hora, cita.tipo_estudio.duracion_minutos)
        citas_por_dia.setdefault(cita.fecha, []).append((rango, cita))
        asignados_por_dia.setdefault(cita.fecha, {}).setdefault(cita.hora, set()).add(etiqueta)

    def _estado_confirmacion(cita):
        """El estado de aceptación de la cita, para que recepción vea de una
        vez si el radiólogo ya la confirmó o todavía está pendiente de
        revisar (aplica sobre todo a COEX/Emergencia IGSS: Privado se agenda
        directo, sin pasar por confirmación)."""
        return 'Pendiente' if cita.estado == Cita.ESTADO_PENDIENTE else 'Confirmada'

    def _resumen_cita(cita):
        radiologo = cita.radiologo
        return {
            'id': cita.id,
            'eliminable': cita.se_puede_eliminar,
            'hora': cita.hora.strftime('%H:%M'),
            'paciente': f'{cita.paciente.nombre} {cita.paciente.apellido}',
            'estudio': cita.tipo_estudio.nombre,
            'convenio': cita.get_convenio_display(),
            'radiologo': (
                (radiologo.get_full_name() or radiologo.username) if radiologo else 'Sin asignar'
            ),
            'estado': _estado_confirmacion(cita),
        }

    def _celda(dia, hora):
        asignados = asignados_por_dia.get(dia, {})
        franja = rango_ocupado_por(dia, hora, PASO_MINUTOS)
        cruces = [
            cita for rango, cita in citas_por_dia.get(dia, [])
            if se_cruzan(franja, rango)
        ]
        etiquetas = sorted({ETIQUETA_CONVENIO_CORTA.get(c.convenio, c.convenio) for c in cruces})
        return {
            'dia': dia,
            'hora': hora,
            'pasado': en_el_pasado(dia, hora),
            'fuera_rango': fuera_de_ventana(dia),
            'asignado': hora in asignados,
            'ocupado': hora not in asignados and bool(cruces),
            'convenios': ', '.join(etiquetas),
            'tiene_pendiente': any(c.estado == Cita.ESTADO_PENDIENTE for c in cruces),
            'citas': [_resumen_cita(c) for c in sorted(cruces, key=lambda c: c.hora)],
        }

    filas = [
        {'hora': hora, 'celdas': [_celda(dia, hora) for dia in dias]}
        for hora in horarios_disponibles()
    ]
    slots_detalle = {
        f"{celda['dia'].isoformat()}|{celda['hora'].strftime('%H:%M')}": celda['citas']
        for fila in filas for celda in fila['celdas'] if celda['citas']
    }

    contexto = {
        'convenio': convenio,
        'convenio_nombre': convenio_nombre,
        'agendar_url_name': f'agendar_cita_{convenio}',
        'dias': list(zip(DIAS_SEMANA, dias)),
        'filas': filas,
        'semana_anterior': inicio - datetime.timedelta(days=7),
        'mostrar_semana_anterior': inicio > inicio_semana(hoy),
        'semana_siguiente': inicio + datetime.timedelta(days=7),
        'mostrar_semana_siguiente': not fuera_de_ventana(inicio + datetime.timedelta(days=7)),
        'reagendar_cita': reagendar_cita,
        'reagendar_url_name': f'confirmar_reagenda_{convenio}' if reagendar_cita else None,
        'procesar_url_name': f'procesar_citas_{convenio}',
        'maximo_emergencias_por_dia': MAXIMO_EMERGENCIAS_POR_DIA,
        'radiologos': radiologos,
        'radiologo_seleccionado': radiologo_seleccionado,
        'slots_detalle': slots_detalle,
    }
    return render(request, 'pacientes/calendario.html', contexto)


def _hay_estudio_duplicado(*, dpi, tipo_estudio, fecha, hora):
    """Evita agendar el mismo estudio dos veces al mismo paciente en el
    mismo horario, aunque se intente desde otro convenio."""
    return Cita.objects.filter(
        paciente__dpi=dpi,
        tipo_estudio=tipo_estudio,
        fecha=fecha,
        hora=hora,
    ).exclude(estado=Cita.ESTADO_RECHAZADA).exists()


def _hay_conflicto_horario(fecha_dt, hora_time, duracion_minutos):
    """¿El horario dado se cruza con alguna cita ya existente ese día?
    (no cuenta las citas rechazadas)."""
    if not fecha_dt or not hora_time:
        return False
    ocupados = [
        rango_ocupado_por(c.fecha, c.hora, c.tipo_estudio.duracion_minutos)
        for c in Cita.objects.filter(fecha=fecha_dt)
        .exclude(estado=Cita.ESTADO_RECHAZADA)
        .select_related('tipo_estudio')
    ]
    rango_nuevo = rango_ocupado_por(fecha_dt, hora_time, duracion_minutos)
    return any(se_cruzan(rango_nuevo, ocupado) for ocupado in ocupados)


@login_required
@user_passes_test(es_recepcionista)
def agendar_cita(request, convenio):
    convenio_nombre = dict(Cita.CONVENIO_CHOICES).get(convenio, convenio)
    calendario_url = reverse(f'calendario_{convenio}')

    datos = request.POST if request.method == 'POST' else request.GET
    fecha = datos.get('fecha')
    hora = datos.get('hora')
    if not fecha or not hora:
        return redirect(calendario_url)

    if request.method == 'POST':
        form = AgendarCitaForm(request.POST, convenio=convenio)
    else:
        inicial = {'fecha': fecha, 'hora': hora}
        if request.GET.get('radiologo'):
            inicial['radiologo'] = request.GET['radiologo']
        form = AgendarCitaForm(initial=inicial, convenio=convenio)
    form.fields['fecha'].widget = forms.HiddenInput()
    form.fields['hora'].widget = forms.HiddenInput()

    # Aviso de si el horario elegido ya tiene otra cita encima: se calcula
    # desde ya (sin esperar a elegir el tipo de estudio) usando PASO_MINUTOS
    # como referencia, para que la advertencia de emergencia aparezca apenas
    # se carga la pantalla. Al enviar el formulario se vuelve a calcular con
    # la duración real del estudio elegido, que es la que manda.
    fecha_dt = fecha if isinstance(fecha, datetime.date) else parse_date(fecha)
    try:
        hora_time = hora if isinstance(hora, datetime.time) else datetime.datetime.strptime(hora, '%H:%M').time()
    except (TypeError, ValueError):
        hora_time = None
    hay_conflicto = _hay_conflicto_horario(fecha_dt, hora_time, PASO_MINUTOS)

    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        if en_el_pasado(cd['fecha'], cd['hora']):
            messages.error(request, 'No se pueden agendar citas en un horario que ya pasó.')
            return redirect(calendario_url)
        if fuera_de_ventana(cd['fecha']):
            messages.error(request, 'Solo se pueden agendar citas hasta 3 semanas después de hoy.')
            return redirect(calendario_url)

        if _hay_estudio_duplicado(
            dpi=cd['dpi'],
            tipo_estudio=cd['tipo_estudio'],
            fecha=cd['fecha'],
            hora=cd['hora'],
        ):
            form.add_error(
                None,
                'Este paciente ya tiene agendado ese mismo estudio en la fecha y hora seleccionadas.',
            )
            return render(request, 'pacientes/agendar_cita.html', {
                'form': form,
                'convenio': convenio,
                'convenio_nombre': convenio_nombre,
                'calendario_url': calendario_url,
                'fecha_valor': fecha,
                'hora_valor': hora,
                'requiere_carnet_igss': convenio in (
                    Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS,
                ),
                'hay_conflicto': hay_conflicto,
            })

        hay_conflicto = _hay_conflicto_horario(cd['fecha'], cd['hora'], cd['tipo_estudio'].duracion_minutos)

        if hay_conflicto and not cd['es_emergencia']:
            form.add_error(
                None,
                'Este horario ya está ocupado por otra cita. Si es una emergencia que debe '
                'agendarse sí o sí en este horario, marcá la casilla de confirmación de '
                'emergencia (más abajo) y volvé a enviar.',
            )
        else:
            if hay_conflicto:
                emergencias_hoy = Cita.objects.filter(
                    fecha=cd['fecha'], es_emergencia_forzada=True,
                ).exclude(estado=Cita.ESTADO_RECHAZADA).count()
                if emergencias_hoy >= MAXIMO_EMERGENCIAS_POR_DIA:
                    messages.error(
                        request,
                        f'Ya se agendaron {MAXIMO_EMERGENCIAS_POR_DIA} citas de emergencia para el '
                        f'{cd["fecha"]}, el máximo permitido por día. Elegí otra fecha.',
                    )
                    return redirect(calendario_url)

            paciente = obtener_o_actualizar_paciente(cd)
            cita = Cita.objects.create(
                paciente=paciente,
                tipo_estudio=cd['tipo_estudio'],
                radiologo=cd['radiologo'],
                convenio=convenio,
                estado=Cita.ESTADO_PENDIENTE,
                fecha=cd['fecha'],
                hora=cd['hora'],
                medico_referente=cd['medico_referente'],
                fecha_sugerida=cd['fecha'],
                hora_sugerida=cd['hora'],
                notas=cd['notas'],
                creada_por=request.user,
                es_emergencia_forzada=hay_conflicto,
            )
            _notificar_cita_asignada(cita)
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_SOLICITAR_CITA,
                descripcion=(
                    ('[EMERGENCIA] ' if hay_conflicto else '')
                    + f'Registró al paciente {paciente.nombre} {paciente.apellido} (DPI {paciente.dpi}) '
                    f'y solicitó cita de {cd["tipo_estudio"]} para {cd["fecha"]} {cd["hora"]} ({convenio}), '
                    f'asignada a {cd["radiologo"]}.'
                    + (
                        ' Se agendó encima de otra cita ya existente por tratarse de una emergencia.'
                        if hay_conflicto else ''
                    )
                ),
            )
            if hay_conflicto:
                messages.success(
                    request,
                    f'Cita de EMERGENCIA agendada para {paciente.nombre} {paciente.apellido} el '
                    f'{cd["fecha"]} a las {cd["hora"]}, encima de otra cita que ya ocupaba ese horario. '
                    f'Se avisó a {cd["radiologo"]} que es una emergencia.',
                )
            else:
                messages.success(
                    request,
                    f'Solicitud enviada a {cd["radiologo"]} para {paciente.nombre} {paciente.apellido} '
                    f'(sugerido: {cd["fecha"]} a las {cd["hora"]}). '
                    'Quedará agendada cuando la radióloga la confirme.',
                )
            return redirect('dashboard')

    if request.method == 'POST':
        avisar_si_correo_no_existe(request, form)

    return render(request, 'pacientes/agendar_cita.html', {
        'form': form,
        'convenio': convenio,
        'convenio_nombre': convenio_nombre,
        'calendario_url': calendario_url,
        'fecha_valor': fecha,
        'hora_valor': hora,
        'requiere_carnet_igss': convenio in (Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS),
        'hay_conflicto': hay_conflicto,
    })


@login_required
@user_passes_test(es_recepcionista)
def agendar_cita_privado(request):
    """Agendamiento del módulo Privado: formulario simple, sin carné IGSS y
    sin revisión del radiólogo. La cita se agenda de una vez (estado
    AGENDADA), se asigna automáticamente al primer radiólogo habilitado para
    ese estudio, y se avisa (sin bloquear) si el turno ya está ocupado por
    otra cita."""
    calendario_url = reverse('calendario_privado')

    datos = request.POST if request.method == 'POST' else request.GET
    fecha_inicial = datos.get('fecha')
    hora_inicial = datos.get('hora')

    if request.method == 'POST':
        form = AgendarCitaPrivadoForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            if en_el_pasado(cd['fecha'], cd['hora']):
                messages.error(request, 'No se pueden agendar citas en un horario que ya pasó.')
                return redirect(calendario_url)
            if fuera_de_ventana(cd['fecha']):
                messages.error(request, 'Solo se pueden agendar citas hasta 3 semanas después de hoy.')
                return redirect(calendario_url)

            if _hay_estudio_duplicado(
                dpi=cd['dpi'],
                tipo_estudio=cd['tipo_estudio'],
                fecha=cd['fecha'],
                hora=cd['hora'],
            ):
                form.add_error(
                    None,
                    'Este paciente ya tiene agendado ese mismo estudio en la fecha y hora seleccionadas.',
                )
                return render(request, 'pacientes/agendar_privado.html', {
                    'form': form,
                    'calendario_url': calendario_url,
                })

            hay_conflicto = _hay_conflicto_horario(
                cd['fecha'], cd['hora'], cd['tipo_estudio'].duracion_minutos,
            )
            # El radiólogo lo resuelve el form (resolver_radiologo_para_estudio):
            # si el estudio tiene uno solo se asigna solo, si tiene varios lo
            # eligió la secretaria.
            radiologo = cd.get('radiologo')

            paciente = obtener_o_actualizar_paciente(cd)
            cita = Cita.objects.create(
                paciente=paciente,
                tipo_estudio=cd['tipo_estudio'],
                radiologo=radiologo,
                convenio=Cita.CONVENIO_PRIVADO,
                estado=Cita.ESTADO_AGENDADA,
                fecha=cd['fecha'],
                hora=cd['hora'],
                fecha_sugerida=cd['fecha'],
                hora_sugerida=cd['hora'],
                notas=cd['motivo'],
                creada_por=request.user,
                revisada_por=request.user,
                revisada_en=timezone.now(),
            )
            ReporteDiario.objects.get_or_create(fecha=cita.fecha, convenio=cita.convenio)
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_SOLICITAR_CITA,
                descripcion=(
                    ('[TURNO OCUPADO] ' if hay_conflicto else '')
                    + f'Agendó cita privada para {paciente.nombre} {paciente.apellido} '
                    f'(DPI {paciente.dpi}): {cd["tipo_estudio"]} '
                    f'para {cd["fecha"]} {cd["hora"]} (cita #{cita.id}).'
                ),
            )
            if hay_conflicto:
                messages.warning(
                    request,
                    f'Cita agendada para {paciente.nombre} {paciente.apellido} el '
                    f'{cd["fecha"]} a las {cd["hora"]}. Ojo: ese turno ya estaba ocupado '
                    'por otra cita.',
                )
            else:
                messages.success(
                    request,
                    f'Cita agendada para {paciente.nombre} {paciente.apellido} el '
                    f'{cd["fecha"]} a las {cd["hora"]}.',
                )
            if radiologo is None:
                messages.warning(
                    request,
                    f'El estudio "{cd["tipo_estudio"]}" no tiene ningún radiólogo habilitado. '
                    'Asignalo desde el admin antes de procesar el estudio.',
                )
            return redirect(f'{reverse("procesar_citas_privado")}?fecha={cita.fecha}')
    else:
        inicial = {}
        if fecha_inicial:
            inicial['fecha'] = fecha_inicial
        if hora_inicial:
            inicial['hora'] = hora_inicial
        if request.GET.get('radiologo'):
            inicial['radiologo'] = request.GET['radiologo']
        form = AgendarCitaPrivadoForm(initial=inicial)
        if fecha_inicial and hora_inicial:
            try:
                hora_dt = datetime.datetime.strptime(hora_inicial, '%H:%M').time()
            except ValueError:
                hora_dt = None
            if hora_dt and _hay_conflicto_horario(parse_date(fecha_inicial), hora_dt, PASO_MINUTOS):
                messages.warning(request, 'Ese turno ya está ocupado por otra cita.')

    if request.method == 'POST':
        avisar_si_correo_no_existe(request, form)

    return render(request, 'pacientes/agendar_privado.html', {
        'form': form,
        'calendario_url': calendario_url,
    })


@login_required
@user_passes_test(es_recepcionista)
def procesar_citas(request, convenio):
    convenio_nombre = dict(Cita.CONVENIO_CHOICES).get(convenio, convenio)

    fecha = parse_date(request.GET.get('fecha', '')) or datetime.date.today()
    citas = (
        Cita.objects.filter(convenio=convenio, fecha=fecha)
        .exclude(estado=Cita.ESTADO_PENDIENTE)
        .select_related('paciente', 'tipo_estudio', 'orden_trabajo')
        .order_by('hora')
    )

    return render(request, 'pacientes/procesar_citas.html', {
        'convenio': convenio,
        'convenio_nombre': convenio_nombre,
        'fecha': fecha,
        'hoy': datetime.date.today(),
        'dia_anterior': fecha - datetime.timedelta(days=1),
        'dia_siguiente': fecha + datetime.timedelta(days=1),
        'citas': citas,
        'calendario_url_name': f'calendario_{convenio}',
        'marcar_llegada_url_name': f'marcar_llegada_{convenio}',
        'generar_orden_url_name': f'generar_orden_{convenio}',
        'marcar_ausente_url_name': f'marcar_ausente_{convenio}',
    })


def _crear_ticket_de_turno(*, request, cita, usuario, prioridad=Ticket.PRIORIDAD_NORMAL, motivo=''):
    """Genera el ticket de la Pantalla de turnos para una cita que acaba de
    marcarse como llegada (COEX/Privado). Si por algún motivo ya existiera
    un ticket para esta cita (doble clic, etc.) no crea uno duplicado."""
    ticket_existente = Ticket.objects.filter(cita=cita).first()
    if ticket_existente:
        return ticket_existente
    ticket = Ticket.objects.create(
        paciente=cita.paciente,
        cita=cita,
        servicio=cita.convenio,
        prioridad=prioridad,
        motivo=motivo,
        registrado_por=usuario,
    )
    Bitacora.registrar(
        request=request,
        usuario=usuario,
        accion=Bitacora.ACCION_REGISTRAR_TICKET,
        descripcion=(
            f'Se generó el turno {ticket.turno} para {ticket.paciente} al marcar su llegada '
            f'(cita #{cita.id}, {cita.get_convenio_display()}).'
        ),
    )
    return ticket


@login_required
@user_passes_test(es_recepcionista)
def marcar_llegada(request, convenio, cita_id):
    cita = get_object_or_404(Cita, id=cita_id, convenio=convenio)
    if request.method == 'POST' and cita.estado in (Cita.ESTADO_AGENDADA, Cita.ESTADO_EN_ESPERA):
        campos = ['hora_llegada']
        cita.hora_llegada = timezone.now()
        if cita.estado == Cita.ESTADO_EN_ESPERA:
            cita.estado = Cita.ESTADO_AGENDADA
            campos.append('estado')
        cita.save(update_fields=campos)
        Bitacora.registrar(
            request=request,
            usuario=request.user,
            accion=Bitacora.ACCION_MARCAR_LLEGADA,
            descripcion=f'Marcó la llegada de {cita.paciente} (cita #{cita.id}).',
        )

        # Se genera el turno de la Pantalla de turnos para COEX/Privado (los
        # de Emergencia IGSS se registran aparte, en "Registrar Ticket",
        # porque llegan sin cita agendada).
        if convenio in (Cita.CONVENIO_COEX, Cita.CONVENIO_PRIVADO):
            ticket = _crear_ticket_de_turno(request=request, cita=cita, usuario=request.user)
            mensaje = f'Se registró la llegada de {cita.paciente} — turno {ticket.turno}.'

            if convenio == Cita.CONVENIO_PRIVADO:
                try:
                    posiciones = int(request.POST.get('adelantar') or 0)
                except ValueError:
                    posiciones = 0
                posiciones = max(0, min(2, posiciones))
                if posiciones:
                    ticket.adelantar(posiciones)
                    Bitacora.registrar(
                        request=request,
                        usuario=request.user,
                        accion=Bitacora.ACCION_ADELANTAR_TICKET,
                        descripcion=(
                            f'Adelantó {posiciones} turno(s) al turno {ticket.turno} de '
                            f'{ticket.paciente} en la Pantalla de turnos.'
                        ),
                    )
                    mensaje += f' Se adelantó {posiciones} turno(s) en la fila de espera.'

            messages.success(request, mensaje)
        else:
            messages.success(request, f'Se registró la llegada de {cita.paciente}.')
    return redirect(f'{reverse(f"procesar_citas_{convenio}")}?fecha={cita.fecha}')


@login_required
@user_passes_test(es_recepcionista)
def generar_orden(request, convenio, cita_id):
    cita = get_object_or_404(Cita, id=cita_id, convenio=convenio)
    volver_url = f'{reverse(f"procesar_citas_{convenio}")}?fecha={cita.fecha}'

    if not cita.hora_llegada:
        messages.error(request, 'Primero hay que marcar la llegada del paciente.')
        return redirect(volver_url)
    if cita.estado not in (Cita.ESTADO_AGENDADA, Cita.ESTADO_EN_ESPERA):
        messages.error(request, 'Esta cita ya no está pendiente de procesar.')
        return redirect(volver_url)

    if request.method == 'POST':
        form = GenerarOrdenForm(request.POST)
        if form.is_valid():
            OrdenTrabajo.objects.create(
                cita=cita,
                motivo=form.cleaned_data['motivo'],
                creada_por=request.user,
            )
            # Cobro pendiente por defecto: bloquea el envío de resultados
            # hasta que Caja lo marque como pagado (ver _cobro_bloquea_envio).
            Cobro.objects.get_or_create(cita=cita)
            cita.estado = Cita.ESTADO_EN_PROCESO
            cita.save(update_fields=['estado'])
            _notificar_orden_pendiente(cita)
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_GENERAR_ORDEN,
                descripcion=f'Generó la orden de trabajo para {cita.paciente} (cita #{cita.id}).',
            )
            messages.success(
                request, f'Orden de trabajo generada y enviada al técnico para {cita.paciente}.'
            )
            return redirect(volver_url)
    else:
        form = GenerarOrdenForm()

    return render(request, 'pacientes/generar_orden.html', {
        'form': form,
        'cita': cita,
        'edad': cita.paciente.edad_en(cita.fecha),
        'volver_url': volver_url,
    })


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
        OrdenTrabajo.objects.filter(cita__estado=Cita.ESTADO_EN_PROCESO)
        .select_related('cita', 'cita__tipo_estudio')
        .prefetch_related('imagenes', 'cita__tipo_estudio__combo_origen__estudios')
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
    (no era un DICOM válido)."""
    if archivo.name.lower().endswith(EXTENSIONES_IMAGEN_DIRECTA):
        ImagenEstudio.objects.create(
            orden=orden, tipo_estudio=tipo_estudio, archivo=archivo, subida_por=usuario,
        )
        return True

    # dicom_a_jpg_memoria consume el stream del archivo al leerlo con
    # pydicom, así que hay que guardar los bytes originales antes.
    archivo.seek(0)
    contenido_original = archivo.read()
    archivo.seek(0)

    jpg_convertido = dicom_a_jpg_memoria(archivo)
    if jpg_convertido:
        nueva_imagen = ImagenEstudio(orden=orden, tipo_estudio=tipo_estudio, subida_por=usuario)
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
    orden = get_object_or_404(OrdenTrabajo, id=orden_id, cita__estado=Cita.ESTADO_EN_PROCESO)
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
    orden = get_object_or_404(OrdenTrabajo, id=orden_id, cita__estado=Cita.ESTADO_EN_PROCESO)
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
    orden = get_object_or_404(OrdenTrabajo, id=orden_id, cita__estado=Cita.ESTADO_EN_PROCESO)
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
        OrdenTrabajo.objects.select_related('cita__paciente', 'cita__tipo_estudio'),
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
    if cita.convenio in (Cita.CONVENIO_COEX, Cita.CONVENIO_PRIVADO):
        return f'{reverse(f"procesar_citas_{cita.convenio}")}?fecha={cita.fecha}'
    return reverse('pantalla_turnos')


@login_required
@user_passes_test(es_recepcionista)
def estudios_por_corregir(request):
    """Estudios que el técnico pidió modificar y recepción todavía no
    actualizó, sin importar la fecha ni el convenio."""
    ordenes = (
        OrdenTrabajo.objects.filter(
            cita__estado=Cita.ESTADO_EN_PROCESO,
            validacion_estado=OrdenTrabajo.VALIDACION_MODIFICACION,
        )
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
        Cita.objects.select_related('paciente', 'tipo_estudio', 'radiologo'),
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
    busqueda = (request.GET.get('q') or '').strip()
    convenio = (request.GET.get('convenio') or '').strip()
    agrupacion = (request.GET.get('agrupacion') or '').strip()
    ordenes = (
        OrdenTrabajo.objects.filter(cita__estado=Cita.ESTADO_EN_PROCESO, imagenes__isnull=False)
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
    cita = get_object_or_404(Cita, id=cita_id, estado=Cita.ESTADO_EN_PROCESO)
    orden = get_object_or_404(OrdenTrabajo, cita=cita)
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

            completos_ids = {i.tipo_estudio_id for i in orden.informes.all() if i.texto or i.archivo}
            faltan = [e.nombre for e in estudios if e.id not in completos_ids]
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
        'estudios_extra': cita.estudios_extra.select_related('tipo_estudio', 'agregado_por').all(),
    })


def _registrar_estudio_extra(request, cita, form):
    """Crea el EstudioExtra a partir de un form ya validado, notifica a
    recepción y lo registra en la bitácora. Lo usan tanto
    agregar_estudio_extra (el endpoint viejo, standalone) como
    adjuntar_informe (cuando se agrega en el mismo envío que el informe)."""
    extra = EstudioExtra.objects.create(
        cita=cita,
        tipo_estudio=form.cleaned_data['tipo_estudio'],
        agregado_por=request.user,
        notas=form.cleaned_data['notas'],
    )
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
    Bitacora.registrar(
        request=request,
        usuario=request.user,
        accion=Bitacora.ACCION_AGREGAR_ESTUDIO_EXTRA,
        descripcion=(
            f'Agregó el estudio extra "{extra.tipo_estudio.nombre}" (Q{extra.precio:.2f}) '
            f'a la cita de {cita.paciente} (cita #{cita.id}).'
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
        Cita,
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
    messages.success(
        request,
        f'Estudio extra "{extra.tipo_estudio.nombre}" agregado y notificado a recepción.',
    )
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
    orden = get_object_or_404(OrdenTrabajo, id=orden_id)
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
    orden = get_object_or_404(OrdenTrabajo, id=orden_id)
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
    orden = get_object_or_404(OrdenTrabajo, id=orden_id)
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


@login_required
@user_passes_test(es_radiologo)
def solicitudes_pendientes(request):
    citas = (
        Cita.objects.filter(estado=Cita.ESTADO_PENDIENTE, radiologo=request.user)
        .select_related('paciente', 'tipo_estudio')
        .order_by('fecha_sugerida', 'hora_sugerida')
    )
    return render(request, 'pacientes/solicitudes_pendientes.html', {'citas': citas})


@login_required
@user_passes_test(es_radiologo)
def revisar_solicitud(request, cita_id):
    cita = get_object_or_404(
        Cita, id=cita_id, estado=Cita.ESTADO_PENDIENTE, radiologo=request.user
    )
    volver_url = reverse('solicitudes_pendientes')
    limite = cita.creada_en.date() + datetime.timedelta(days=LIMITE_DIAS_ADELANTE)

    if request.method == 'POST':
        accion = request.POST.get('accion')

        if accion == 'rechazar':
            cita.estado = Cita.ESTADO_RECHAZADA
            cita.motivo_rechazo = request.POST.get('motivo_rechazo', '').strip()
            cita.revisada_por = request.user
            cita.revisada_en = timezone.now()
            cita.save(update_fields=['estado', 'motivo_rechazo', 'revisada_por', 'revisada_en'])
            _notificar_cita_rechazada(cita)
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_RECHAZAR_CITA,
                descripcion=(
                    f'Rechazó la solicitud de cita de {cita.paciente} (cita #{cita.id}). '
                    f'Motivo: {cita.motivo_rechazo or "—"}'
                ),
            )
            messages.success(request, f'Solicitud de {cita.paciente} rechazada.')
            return redirect(volver_url)

        fecha = parse_date(request.POST.get('fecha', ''))
        hora_str = request.POST.get('hora', '')
        try:
            hora = datetime.datetime.strptime(hora_str, '%H:%M').time()
        except ValueError:
            hora = None

        if not fecha or not hora:
            messages.error(request, 'Fecha u hora inválida.')
            return redirect(request.path)
        if en_el_pasado(fecha, hora):
            messages.error(request, 'No se puede confirmar una cita en un horario que ya pasó.')
            return redirect(request.path)
        if fecha > limite:
            messages.error(
                request,
                f'La cita debe quedar confirmada antes del {limite} (3 semanas desde que se solicitó).',
            )
            return redirect(request.path)

        cita.fecha = fecha
        cita.hora = hora
        cita.estado = Cita.ESTADO_AGENDADA
        cita.revisada_por = request.user
        cita.revisada_en = timezone.now()
        cita.save(update_fields=['fecha', 'hora', 'estado', 'revisada_por', 'revisada_en'])
        ReporteDiario.objects.get_or_create(fecha=cita.fecha, convenio=cita.convenio)
        _notificar_cita_confirmada(cita)
        Bitacora.registrar(
            request=request,
            usuario=request.user,
            accion=Bitacora.ACCION_CONFIRMAR_CITA,
            descripcion=(
                f'Confirmó la cita de {cita.paciente} para el {fecha} '
                f'a las {hora_str} (cita #{cita.id}).'
            ),
        )
        messages.success(request, f'Cita de {cita.paciente} confirmada para el {fecha} a las {hora_str}.')
        return redirect(volver_url)

    return render(request, 'pacientes/revisar_solicitud.html', {
        'cita': cita,
        'edad': cita.paciente.edad_en(cita.fecha_sugerida or cita.fecha),
        'limite': limite,
        'volver_url': volver_url,
    })


@login_required
@user_passes_test(es_recepcionista)
def marcar_ausente(request, convenio, cita_id):
    cita = get_object_or_404(Cita, id=cita_id, convenio=convenio)
    if request.method == 'POST':
        if cita.fecha > datetime.date.today():
            messages.error(request, 'No se puede marcar ausente una cita antes de la fecha en que le toca.')
        else:
            cita.estado = Cita.ESTADO_AUSENTE
            cita.save(update_fields=['estado'])
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_MARCAR_AUSENTE,
                descripcion=f'Marcó como ausente a {cita.paciente} (cita #{cita.id}).',
            )
            messages.success(request, f'Cita de {cita.paciente} marcada como ausente.')
    return redirect(f'{reverse(f"procesar_citas_{convenio}")}?fecha={cita.fecha}')


@login_required
@user_passes_test(es_recepcionista)
def confirmar_reagenda(request, convenio, cita_id):
    cita = get_object_or_404(Cita, id=cita_id, convenio=convenio)
    calendario_url = reverse(f'calendario_{convenio}')

    if cita.estado != Cita.ESTADO_AUSENTE:
        messages.error(request, 'Solo se pueden reagendar citas marcadas como ausente.')
        return redirect(f'{reverse(f"procesar_citas_{convenio}")}?fecha={cita.fecha}')

    datos = request.POST if request.method == 'POST' else request.GET
    fecha = parse_date(datos.get('fecha', ''))
    hora = datos.get('hora')
    if not fecha or not hora:
        return redirect(f'{calendario_url}?reagendar={cita.id}')

    if request.method == 'POST':
        hora_valor = datetime.datetime.strptime(hora, '%H:%M').time()
        if en_el_pasado(fecha, hora_valor):
            messages.error(request, 'No se pueden reagendar citas a un horario que ya pasó.')
            return redirect(f'{calendario_url}?reagendar={cita.id}')
        if fuera_de_ventana(fecha):
            messages.error(request, 'Solo se pueden reagendar citas hasta 3 semanas después de hoy.')
            return redirect(f'{calendario_url}?reagendar={cita.id}')

        ocupados = [
            rango_ocupado_por(c.fecha, c.hora, c.tipo_estudio.duracion_minutos)
            for c in Cita.objects.filter(fecha=fecha)
            .exclude(estado=Cita.ESTADO_RECHAZADA)
            .exclude(id=cita.id)
            .select_related('tipo_estudio')
        ]
        rango_nuevo = rango_ocupado_por(fecha, hora_valor, cita.tipo_estudio.duracion_minutos)
        if any(se_cruzan(rango_nuevo, ocupado) for ocupado in ocupados):
            messages.error(request, 'Ese horario ya no está disponible: se cruza con otra cita.')
            return redirect(f'{calendario_url}?reagendar={cita.id}')

        cita.fecha = fecha
        cita.hora = hora_valor
        cita.estado = Cita.ESTADO_AGENDADA
        cita.save(update_fields=['fecha', 'hora', 'estado'])
        ReporteDiario.objects.get_or_create(fecha=cita.fecha, convenio=cita.convenio)
        Bitacora.registrar(
            request=request,
            usuario=request.user,
            accion=Bitacora.ACCION_REAGENDAR_CITA,
            descripcion=(
                f'Reagendó la cita de {cita.paciente} para el {fecha} '
                f'a las {hora} (cita #{cita.id}).'
            ),
        )
        messages.success(request, f'Cita de {cita.paciente} reagendada para el {fecha} a las {hora}.')
        return redirect(f'{reverse(f"procesar_citas_{convenio}")}?fecha={fecha}')

    return render(request, 'pacientes/reagendar_confirmar.html', {
        'cita': cita,
        'nueva_fecha': fecha,
        'nueva_hora': hora,
        'calendario_url': f'{calendario_url}?reagendar={cita.id}',
    })


def _volver_seguro(request, por_defecto):
    """Adónde regresar después de una acción: la página desde la que se
    hizo (campo `volver`), solo si es una dirección de este mismo sitio."""
    destino = request.POST.get('volver', '')
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return destino
    return por_defecto


@login_required
@user_passes_test(es_recepcionista)
@require_POST
def eliminar_cita(request, cita_id):
    """Elimina del calendario una cita que todavía no entró al flujo de
    trabajo (el paciente ya no quiere hacerse el estudio), para que deje de
    ocupar el horario. Queda registrado en la bitácora."""
    cita = get_object_or_404(
        Cita.objects.select_related('paciente', 'tipo_estudio', 'radiologo', 'orden_trabajo', 'cobro'),
        id=cita_id,
    )
    volver = _volver_seguro(request, reverse(f'calendario_{cita.convenio}'))

    if not cita.se_puede_eliminar:
        messages.error(
            request,
            'Esta cita ya está en proceso o ya se atendió: no se puede eliminar del calendario.',
        )
        return redirect(volver)
    if ReporteDiario.objects.filter(
        fecha=cita.fecha, convenio=cita.convenio, estado=ReporteDiario.ESTADO_ENVIADO,
    ).exists():
        messages.error(
            request,
            'El reporte diario de ese día y convenio ya se envió: la cita no se puede eliminar.',
        )
        return redirect(volver)

    paciente = f'{cita.paciente.nombre} {cita.paciente.apellido}'
    detalle = (
        f'{cita.tipo_estudio.nombre}, {cita.get_convenio_display()}, '
        f'{cita.fecha:%d/%m/%Y} {cita.hora:%H:%M}'
    )
    radiologo = cita.radiologo
    try:
        with transaction.atomic():
            # Si el paciente ya había llegado, su turno sale de la fila.
            cita.ticket_origen.filter(estado=Ticket.ESTADO_EN_ESPERA).update(
                estado=Ticket.ESTADO_AUSENTE,
            )
            cita_id_original = cita.id
            cita.delete()
    except ProtectedError:
        messages.error(request, 'Esta cita ya tiene datos asociados y no se puede eliminar.')
        return redirect(volver)

    if radiologo:
        Notificacion.notificar(
            destinatario=radiologo,
            tipo=Notificacion.TIPO_CITA_CANCELADA,
            mensaje=f'Cita cancelada por recepción: {detalle} — {paciente}.',
            url=reverse('solicitudes_pendientes'),
        )
    Bitacora.registrar(
        request=request, usuario=request.user,
        accion=Bitacora.ACCION_ELIMINAR_CITA,
        descripcion=f'Eliminó la cita de {paciente} ({detalle}, cita #{cita_id_original}).',
    )
    messages.success(request, f'Cita de {paciente} eliminada del calendario.')
    return redirect(volver)


# Registrar Ticket: check-in de pacientes que llegan a Emergencia IGSS sin
# cita agendada. Genera un turno numerado (ver Ticket.save) para la fila de
# atención. Siempre entra como prioridad "Urgente": es la única forma de
# obtener esa prioridad en la Pantalla de turnos (COEX/Privado son siempre
# "Normal", ver _crear_ticket_de_turno).
@login_required
@user_passes_test(es_recepcionista)
def registrar_ticket_emergencia(request):
    volver_url = reverse('pantalla_placeholder', kwargs={'clave': 'emergencia_igss'})

    if request.method == 'POST':
        form = RegistrarTicketForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            paciente = obtener_o_actualizar_paciente(cd)
            ticket = Ticket.objects.create(
                paciente=paciente,
                servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
                prioridad=Ticket.PRIORIDAD_URGENTE,
                motivo=cd['motivo'],
                registrado_por=request.user,
            )
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_REGISTRAR_TICKET,
                descripcion=(
                    f'Registró el ticket {ticket.turno} de Emergencia IGSS para '
                    f'{paciente.nombre} {paciente.apellido} (DPI {paciente.dpi}).'
                ),
            )
            messages.success(
                request, f'Ticket {ticket.turno} registrado para {paciente.nombre} {paciente.apellido}.'
            )
            return redirect('pantalla_turnos')
    else:
        form = RegistrarTicketForm()

    if request.method == 'POST':
        avisar_si_correo_no_existe(request, form)

    return render(request, 'pacientes/registrar_ticket_emergencia.html', {
        'form': form,
        'volver_url': volver_url,
    })


@login_required
@user_passes_test(es_recepcionista)
def pantalla_turnos(request):
    """Fila de espera unificada de COEX + Privado + Emergencia IGSS. El
    primero de la cola (mayor prioridad y, entre iguales, el que lleva más
    tiempo esperando o fue adelantado) se resalta como el turno actual;
    "Siguiente" lo marca atendido y pasa al que sigue.

    Solo el día de hoy muestra la fila en vivo (nada más los que siguen en
    espera, con el botón "Siguiente" habilitado). Los demás días muestran el
    historial completo de turnos de ese día, de solo lectura."""
    hoy = timezone.localdate()
    fecha = parse_date(request.GET.get('fecha', '')) or hoy
    es_hoy = fecha == hoy

    tickets_del_dia = Ticket.del_dia(fecha).select_related(
        'paciente', 'cita__radiologo', 'cita__tipo_estudio',
    )
    if es_hoy:
        cola = tickets_del_dia.filter(estado=Ticket.ESTADO_EN_ESPERA).order_by('-prioridad', 'orden')
    else:
        cola = tickets_del_dia.order_by('-prioridad', 'orden')

    return render(request, 'pacientes/pantalla_turnos.html', {
        'cola': cola,
        'actual': cola.first() if es_hoy else None,
        'fecha': fecha,
        'es_hoy': es_hoy,
        'hoy': hoy,
        'dia_anterior': fecha - datetime.timedelta(days=1),
        'dia_siguiente': fecha + datetime.timedelta(days=1),
    })


# Sala según la modalidad del estudio (no según el radiólogo asignado):
# todos los estudios de una misma modalidad se atienden en el mismo
# equipo/sala, sin importar qué radiólogo esté de turno ahí.
SALA_POR_MODALIDAD = {
    TipoEstudio.MODALIDAD_RX: 'Sala 1',
    TipoEstudio.MODALIDAD_RX_CONTRASTE: 'Sala 1',
    TipoEstudio.MODALIDAD_MAMO_DENSIT: 'Sala 2',
    TipoEstudio.MODALIDAD_TAC: 'Sala 3',
    TipoEstudio.MODALIDAD_USG: 'Sala 4',
}


def _turno_actual_sala_espera(hoy):
    """El último turno llamado (marcado atendido) hoy, o None."""
    return (
        Ticket.del_dia(hoy)
        .select_related('paciente', 'cita__radiologo', 'cita__tipo_estudio')
        .filter(estado=Ticket.ESTADO_ATENDIDO)
        .order_by('-atendido_en')
        .first()
    )


def _proximos_sala_espera(hoy):
    return (
        Ticket.del_dia(hoy)
        .filter(estado=Ticket.ESTADO_EN_ESPERA)
        .order_by('-prioridad', 'orden')[:4]
    )


def _actual_sala_espera_dict(actual):
    """Datos del turno actual para la pantalla pública: nombre completo del
    paciente, radiólogo asignado y la sala del estudio (según su
    modalidad — no según el radiólogo). NO incluye el tipo de estudio en
    sí (privacidad)."""
    if actual is None:
        return None
    radiologo = actual.cita.radiologo if actual.cita_id else None
    tipo_estudio = actual.cita.tipo_estudio if actual.cita_id else None
    return {
        'turno': actual.turno,
        'paciente': f'{actual.paciente.nombre} {actual.paciente.apellido}'.strip(),
        'radiologo': (
            (radiologo.get_full_name() or radiologo.username) if radiologo else ''
        ),
        'sala': (SALA_POR_MODALIDAD.get(tipo_estudio.modalidad, '') if tipo_estudio else ''),
    }


def pantalla_sala_espera(request):
    """Pantalla pública para el televisor de la sala de espera (sin login:
    se abre directo en la TV). Muestra el último turno llamado — el que se
    acaba de marcar atendido en pantalla_turnos, con "favor de pasar", el
    nombre completo del paciente, su radiólogo y la sala (según la
    modalidad del estudio) — y los próximos en espera. Se actualiza sola
    cada pocos segundos vía estado_sala_espera."""
    hoy = timezone.localdate()
    actual = _turno_actual_sala_espera(hoy)
    return render(request, 'pacientes/pantalla_sala_espera.html', {
        'actual': _actual_sala_espera_dict(actual),
        'proximos': _proximos_sala_espera(hoy),
        'hoy': hoy,
    })


def estado_sala_espera(request):
    """JSON con el estado de la sala de espera, para que la pantalla del
    televisor se refresque sola sin recargar toda la página. Público, igual
    que pantalla_sala_espera."""
    hoy = timezone.localdate()
    return JsonResponse({
        'actual': _actual_sala_espera_dict(_turno_actual_sala_espera(hoy)),
        'proximos': [{'turno': t.turno} for t in _proximos_sala_espera(hoy)],
    })


@login_required
@user_passes_test(es_recepcionista)
@require_POST
def avanzar_turno(request, ticket_id):
    """Marca este ticket como atendido (desaparece de la Pantalla de turnos)
    y de paso el siguiente en la cola pasa a ser el turno actual."""
    ticket = get_object_or_404(Ticket, id=ticket_id, estado=Ticket.ESTADO_EN_ESPERA)
    ticket.estado = Ticket.ESTADO_ATENDIDO
    ticket.atendido_en = timezone.now()
    ticket.save(update_fields=['estado', 'atendido_en'])
    Bitacora.registrar(
        request=request,
        usuario=request.user,
        accion=Bitacora.ACCION_AVANZAR_TURNO,
        descripcion=f'Avanzó la Pantalla de turnos: turno {ticket.turno} ({ticket.paciente}) atendido.',
    )
    messages.success(request, f'Turno {ticket.turno} atendido.')
    return redirect('pantalla_turnos')


@login_required
@user_passes_test(es_recepcionista)
@require_POST
def mover_turno(request, ticket_id):
    """Sube o baja un turno una posición en la fila de espera (respetando la
    prioridad). `direccion` = 'subir' | 'bajar'."""
    ticket = get_object_or_404(Ticket, id=ticket_id, estado=Ticket.ESTADO_EN_ESPERA)
    direccion = request.POST.get('direccion')
    if direccion == 'subir':
        ticket.mover(-1)
    elif direccion == 'bajar':
        ticket.mover(1)
    else:
        return redirect('pantalla_turnos')
    Bitacora.registrar(
        request=request, usuario=request.user,
        accion=Bitacora.ACCION_ADELANTAR_TICKET,
        descripcion=(
            f'Movió el turno {ticket.turno} ({ticket.paciente}) '
            f'{"hacia arriba" if direccion == "subir" else "hacia abajo"} en la fila.'
        ),
    )
    return redirect('pantalla_turnos')


@login_required
@user_passes_test(es_recepcionista)
@require_POST
def eliminar_turno(request, ticket_id):
    """Saca de la fila de espera a un paciente que ya no quiere pasar. El
    turno queda como "Ausente" (para el historial del día) y deja de aparecer
    en la Pantalla de turnos y en la TV de la sala de espera. Si venía de una
    cita que todavía no se procesó, se le quita la llegada para que la cita
    pueda marcarse ausente, reagendarse o eliminarse como cualquier otra."""
    ticket = get_object_or_404(
        Ticket.objects.select_related('paciente', 'cita'),
        id=ticket_id, estado=Ticket.ESTADO_EN_ESPERA,
    )
    ticket.estado = Ticket.ESTADO_AUSENTE
    ticket.save(update_fields=['estado'])

    cita = ticket.cita
    if (
        cita is not None
        and cita.estado in (Cita.ESTADO_AGENDADA, Cita.ESTADO_EN_ESPERA)
        and not hasattr(cita, 'orden_trabajo')
        and cita.hora_llegada
    ):
        cita.hora_llegada = None
        cita.save(update_fields=['hora_llegada'])

    Bitacora.registrar(
        request=request, usuario=request.user,
        accion=Bitacora.ACCION_ELIMINAR_TURNO,
        descripcion=(
            f'Eliminó el turno {ticket.turno} ({ticket.paciente}) de la fila de espera: '
            'el paciente ya no va a pasar.'
        ),
    )
    messages.success(request, f'Turno {ticket.turno} eliminado de la fila de espera.')
    return redirect('pantalla_turnos')


@login_required
@user_passes_test(es_recepcionista)
@require_POST
def procesar_turno(request, ticket_id):
    """Genera de una vez la orden de trabajo del turno y la manda al técnico.
    Para los turnos de COEX/Privado usa la cita que ya existe; los de
    Emergencia IGSS (sin cita) van a la pantalla que pide el tipo de estudio."""
    ticket = get_object_or_404(Ticket, id=ticket_id, estado=Ticket.ESTADO_EN_ESPERA)

    if not ticket.cita_id:
        if ticket.servicio == Ticket.SERVICIO_EMERGENCIA_IGSS:
            return redirect('procesar_ticket_emergencia', ticket_id=ticket.id)
        messages.error(
            request,
            f'El turno {ticket.turno} no tiene una cita asociada, no se puede procesar desde acá.',
        )
        return redirect('pantalla_turnos')

    cita = ticket.cita

    if hasattr(cita, 'orden_trabajo') or cita.estado in (
        Cita.ESTADO_EN_PROCESO, Cita.ESTADO_PROCESADA,
    ):
        # La orden ya existe (se generó por otro lado o el estudio ya avanzó):
        # solo se saca el turno de la fila.
        messages.info(
            request,
            f'El turno {ticket.turno} ya tenía la orden generada. Se marcó como atendido.',
        )
    elif cita.estado == Cita.ESTADO_AUSENTE:
        messages.warning(
            request,
            f'La cita del turno {ticket.turno} está marcada como ausente. Se sacó de la fila; '
            'si el paciente sí llegó, reagendá la cita desde "Procesar cita".',
        )
    elif cita.estado in (Cita.ESTADO_AGENDADA, Cita.ESTADO_EN_ESPERA):
        OrdenTrabajo.objects.create(
            cita=cita,
            motivo=(cita.notas or ticket.motivo or 'Sin indicación clínica registrada.'),
            creada_por=request.user,
        )
        Cobro.objects.get_or_create(cita=cita)
        cita.estado = Cita.ESTADO_EN_PROCESO
        cita.save(update_fields=['estado'])
        _notificar_orden_pendiente(cita)
        Bitacora.registrar(
            request=request, usuario=request.user,
            accion=Bitacora.ACCION_GENERAR_ORDEN,
            descripcion=(
                f'Generó la orden de trabajo desde la Pantalla de turnos para '
                f'{cita.paciente} (turno {ticket.turno}, cita #{cita.id}).'
            ),
        )
        messages.success(
            request,
            f'Orden enviada al técnico para {cita.paciente}. Turno {ticket.turno} atendido.',
        )
    else:
        messages.error(
            request,
            f'La cita del turno {ticket.turno} está en un estado ({cita.get_estado_display()}) '
            'que no se puede procesar. Se sacó de la fila.',
        )

    ticket.estado = Ticket.ESTADO_ATENDIDO
    ticket.atendido_en = timezone.now()
    ticket.save(update_fields=['estado', 'atendido_en'])
    return redirect('pantalla_turnos')


@login_required
@user_passes_test(es_recepcionista)
def procesar_ticket_emergencia(request, ticket_id):
    """Convierte el ticket en una cita EN_PROCESO + orden de trabajo, lista
    para que el técnico la vea en 'Órdenes pendientes'. Se salta agendado y
    revisión del radiólogo porque el paciente ya está en la clínica."""
    ticket = get_object_or_404(Ticket, id=ticket_id, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS)
    volver_url = reverse('pantalla_turnos')

    if ticket.estado != Ticket.ESTADO_EN_ESPERA:
        messages.error(request, f'El ticket {ticket.turno} ya fue procesado.')
        return redirect(volver_url)

    if request.method == 'POST':
        form = ProcesarTicketForm(request.POST)
        if form.is_valid():
            ahora = timezone.localtime()
            cita = Cita.objects.create(
                paciente=ticket.paciente,
                tipo_estudio=form.cleaned_data['tipo_estudio'],
                convenio=Cita.CONVENIO_EMERGENCIA_IGSS,
                estado=Cita.ESTADO_EN_PROCESO,
                fecha=ahora.date(),
                hora=ahora.time(),
                hora_llegada=ticket.creado_en,
                notas=ticket.motivo,
                creada_por=request.user,
            )
            OrdenTrabajo.objects.create(
                cita=cita,
                motivo=form.cleaned_data['motivo'],
                creada_por=request.user,
            )
            Cobro.objects.get_or_create(cita=cita)
            ticket.estado = Ticket.ESTADO_ATENDIDO
            ticket.atendido_en = timezone.now()
            ticket.cita = cita
            ticket.save(update_fields=['estado', 'atendido_en', 'cita'])
            _notificar_orden_pendiente(cita)
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_PROCESAR_TICKET,
                descripcion=(
                    f'Procesó el ticket {ticket.turno} de Emergencia IGSS y generó la orden de trabajo '
                    f'para {ticket.paciente} (cita #{cita.id}).'
                ),
            )
            messages.success(request, f'Ticket {ticket.turno} procesado: la orden ya está con el técnico.')
            return redirect(volver_url)
    else:
        form = ProcesarTicketForm(initial={'motivo': ticket.motivo})

    return render(request, 'pacientes/procesar_ticket_emergencia.html', {
        'form': form,
        'ticket': ticket,
        'volver_url': volver_url,
    })


MAX_NOTIFICACIONES_EN_CAMPANITA = 20


@login_required
def notificaciones_pendientes(request):
    """Endpoint que la campanita de notificaciones consulta cada cierto
    tiempo (ver includes/notificaciones.html) para saber si hay avisos
    nuevos y hacer sonar el aviso."""
    pendientes = request.user.notificaciones.filter(leida=False)
    notificaciones = list(pendientes[:MAX_NOTIFICACIONES_EN_CAMPANITA])
    return JsonResponse({
        'no_leidas': pendientes.count(),
        'notificaciones': [
            {
                'id': n.id,
                'tipo': n.tipo,
                'mensaje': n.mensaje,
                'url': n.url,
                'creada_en': timezone.localtime(n.creada_en).strftime('%d/%m %H:%M'),
            }
            for n in notificaciones
        ],
    })


@login_required
def marcar_notificacion_leida(request, notificacion_id):
    if request.method == 'POST':
        # Los avisos de "datos de paciente pendientes" no se pueden cerrar a
        # mano: se apagan solos cuando el dato realmente se completa (ver
        # completar_datos_paciente). Se valida también aquí, no solo en el
        # JS, para que no se puedan cerrar llamando el endpoint directo.
        request.user.notificaciones.filter(id=notificacion_id).exclude(
            tipo=Notificacion.TIPO_DATOS_PACIENTE_PENDIENTES,
        ).update(leida=True)
    return JsonResponse({'ok': True})


@login_required
def marcar_notificaciones_leidas(request):
    if request.method == 'POST':
        request.user.notificaciones.filter(leida=False).exclude(
            tipo=Notificacion.TIPO_DATOS_PACIENTE_PENDIENTES,
        ).update(leida=True)
    return JsonResponse({'ok': True})


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
    for indice, cita in enumerate(reporte.citas(), start=1):
        tecnico = cita.tecnico_asignado
        filas.append({
            'no': indice,
            'cita_id': cita.id,
            'hora': cita.hora.strftime('%H:%M'),
            'paciente': f'{cita.paciente.nombre} {cita.paciente.apellido}',
            'edad': cita.paciente.edad_en(cita.fecha),
            'estudio': cita.tipo_estudio.nombre,
            'tecnico': (tecnico.get_full_name() or tecnico.username) if tecnico else '',
            'medico_referente': cita.medico_referente,
            'emerg': 'X' if cita.convenio == Cita.CONVENIO_EMERGENCIA_IGSS else '',
            'radiologo': (
                (cita.radiologo.get_full_name() or cita.radiologo.username) if cita.radiologo else ''
            ),
            'precio': cita.precio,
            'ausente': cita.estado == Cita.ESTADO_AUSENTE,
        })
    return filas


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

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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

    datos = [COLUMNAS_REPORTE]
    for fila in filas:
        datos.append([
            fila['no'], fila['hora'], fila['paciente'], fila['edad'] if fila['edad'] is not None else '',
            fila['estudio'], fila['tecnico'], fila['medico_referente'], fila['emerg'], fila['radiologo'],
            f"Q{fila['precio']:.2f}",
        ])
    datos.append(['', '', '', '', '', '', '', '', 'TOTAL DEL DÍA', f'Q{reporte.total():.2f}'])

    tabla = Table(datos, repeatRows=1)
    ultima_fila = len(datos) - 1
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c4b5fd')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('SPAN', (0, ultima_fila), (-3, ultima_fila)),
        ('BACKGROUND', (-2, ultima_fila), (-1, ultima_fila), colors.HexColor('#fef08a')),
        ('FONTNAME', (-2, ultima_fila), (-1, ultima_fila), 'Helvetica-Bold'),
    ]))
    doc.build([titulo, Spacer(1, 12), tabla])
    return buffer.getvalue()


def _reporte_xlsx_bytes(reporte, filas):
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = 'Reporte'

    ws.merge_cells('A1:J1')
    ws['A1'] = f'INFORME DIARIO "{reporte.get_convenio_display().upper()}"'
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = Alignment(horizontal='center')

    ws.merge_cells('A2:J2')
    ws['A2'] = f'FECHA: {_fecha_larga_es(reporte.fecha).upper()}'
    ws['A2'].alignment = Alignment(horizontal='center')

    ws.append([])
    ws.append(COLUMNAS_REPORTE)
    for celda in ws[ws.max_row]:
        celda.font = Font(bold=True, color='FFFFFF')
        celda.fill = PatternFill('solid', fgColor='7C3AED')

    for fila in filas:
        ws.append([
            fila['no'], fila['hora'], fila['paciente'], fila['edad'], fila['estudio'],
            fila['tecnico'], fila['medico_referente'], fila['emerg'], fila['radiologo'],
            float(fila['precio']),
        ])

    fila_total = ws.max_row + 1
    ws.cell(row=fila_total, column=9, value='TOTAL DEL DÍA').font = Font(bold=True)
    celda_total = ws.cell(row=fila_total, column=10, value=float(reporte.total()))
    celda_total.font = Font(bold=True)
    celda_total.fill = PatternFill('solid', fgColor='FEF08A')

    from openpyxl.utils import get_column_letter

    encabezados_fila = 4
    for indice_columna in range(1, len(COLUMNAS_REPORTE) + 1):
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
        Cita.objects.filter(fecha__year=anio)
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
        Cita.objects.exclude(estado__in=(Cita.ESTADO_PENDIENTE, Cita.ESTADO_RECHAZADA))
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
        .values_list('fecha', flat=True)
        .distinct()
    )
    fechas_existentes = set(
        ReporteDiario.objects.filter(convenio=convenio).values_list('fecha', flat=True)
    )
    for fecha in fechas_con_citas:
        if fecha not in fechas_existentes:
            ReporteDiario.objects.get_or_create(fecha=fecha, convenio=convenio)

    # Los reportes ya creados son el registro permanente: una vez que
    # existen, deben seguir apareciendo aunque las citas que los originaron
    # cambien después (se reagenden a otra fecha, se rechacen, etc.). Por
    # eso se listan desde ReporteDiario y no recalculando a partir de Cita
    # en cada visita. Solo se muestran días anteriores a hoy: el reporte de
    # un día que todavía no terminó puede cambiar (citas que se cancelan,
    # reagendan o completan durante el día), así que hasta que el día pasa
    # no se puede confiar en el conteo de estudios realizados / cancelados /
    # reagendados / finalizados.
    reportes = ReporteDiario.objects.filter(
        convenio=convenio, fecha__lt=timezone.localdate(),
    ).order_by('-fecha')
    if solo_enviados:
        reportes = reportes.filter(estado=ReporteDiario.ESTADO_ENVIADO)

    return render(request, 'pacientes/lista_reportes_diarios.html', {
        'convenio': convenio,
        'convenio_nombre': convenio_nombre,
        'reportes': reportes,
        'solo_enviados': solo_enviados,
    })


@login_required
@user_passes_test(puede_ver_reportes_diarios)
def ver_reporte_diario(request, convenio, fecha):
    _validar_convenio(convenio)
    fecha_valor = parse_date(fecha)
    if not fecha_valor:
        raise Http404('Fecha no válida.')

    reporte = get_object_or_404(ReporteDiario, convenio=convenio, fecha=fecha_valor)
    solo_lectura = _solo_ve_reportes_enviados(request.user)
    if solo_lectura and reporte.estado != ReporteDiario.ESTADO_ENVIADO:
        raise Http404('Este reporte todavía no fue enviado.')

    editable = not solo_lectura and reporte.estado == ReporteDiario.ESTADO_BORRADOR

    if request.method == 'POST':
        if not editable:
            messages.error(request, 'Este reporte ya no se puede editar.')
            return redirect(request.path)
        for cita in reporte.citas():
            valor = request.POST.get(f'medico_referente_{cita.id}', '').strip()
            if valor != cita.medico_referente:
                cita.medico_referente = valor
                cita.save(update_fields=['medico_referente'])
        messages.success(request, 'Cambios guardados.')
        return redirect(request.path)

    pacientes_pendientes = _pacientes_con_datos_pendientes(reporte)
    return render(request, 'pacientes/reporte_diario.html', {
        'reporte': reporte,
        'convenio_nombre': dict(Cita.CONVENIO_CHOICES).get(convenio, convenio),
        'columnas': COLUMNAS_REPORTE,
        'filas': _filas_reporte(reporte),
        'total': reporte.total(),
        'editable': editable,
        'solo_lectura': solo_lectura,
        'lista_url_name': f'lista_reportes_diarios_{convenio}',
        'pacientes_pendientes': pacientes_pendientes,
    })


@login_required
@user_passes_test(es_recepcionista)
def enviar_reporte_diario(request, convenio, fecha):
    _validar_convenio(convenio)
    fecha_valor = parse_date(fecha)
    if not fecha_valor:
        raise Http404('Fecha no válida.')

    reporte = get_object_or_404(ReporteDiario, convenio=convenio, fecha=fecha_valor)
    volver_url = reverse('ver_reporte_diario', args=[convenio, fecha])

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
    reporte = get_object_or_404(
        ReporteDiario, convenio=convenio, fecha=fecha_valor, estado=ReporteDiario.ESTADO_ENVIADO,
    )
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
    reporte = get_object_or_404(
        ReporteDiario, convenio=convenio, fecha=fecha_valor, estado=ReporteDiario.ESTADO_ENVIADO,
    )
    contenido = _reporte_xlsx_bytes(reporte, _filas_reporte(reporte))
    respuesta = HttpResponse(
        contenido, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    respuesta['Content-Disposition'] = f'attachment; filename="reporte_{convenio}_{fecha_valor}.xlsx"'
    return respuesta


# ---------------------------------------------------------------------------
# Visor web público del estudio
#
# El correo de resultados manda un link estilo PACS:
#   /visor/?studyId=<id de la orden>&tab=images&ac=<token en base64>
#
#   - studyId: identifica el estudio (no es secreto)
#   - ac: token de acceso (UUID en base64; sin esto no abre)
#
# Para abrirlo el paciente ingresa además los últimos 4 dígitos de su DPI;
# tras eso queda autorizado en la sesión y puede ver las imágenes que la
# radióloga dejó seleccionadas y descargar el informe. No requiere login.
# ---------------------------------------------------------------------------

VISOR_MAX_INTENTOS = 5


def _ac_a_token(ac):
    """Decodifica el parámetro ac (base64 url-safe, sin padding) al token."""
    try:
        relleno = '=' * (-len(ac) % 4)
        return base64.urlsafe_b64decode(ac + relleno).decode('ascii')
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


def _token_a_ac(token):
    return base64.urlsafe_b64encode(str(token).encode('ascii')).decode('ascii').rstrip('=')


def _visor_orden_desde_request(request):
    study_id = request.GET.get('studyId')
    token = _ac_a_token(request.GET.get('ac') or '')
    if not (study_id or '').isdigit() or not token:
        raise Http404
    orden = get_object_or_404(
        OrdenTrabajo.objects.select_related('cita__paciente', 'cita__tipo_estudio'),
        id=study_id, token_publico=token,
    )
    if not orden.resultados_enviados_en:
        raise Http404
    return orden


def visor_estudio(request):
    orden = _visor_orden_desde_request(request)
    paciente = orden.cita.paciente
    clave_ok = f'visor_ok_{orden.id}'
    clave_intentos = f'visor_intentos_{orden.id}'
    qs = request.META.get('QUERY_STRING', '')

    if request.session.get(clave_ok) is not True:
        intentos = request.session.get(clave_intentos, 0)
        contexto = {'paciente': paciente, 'query_string': qs}

        if request.method == 'POST':
            if intentos >= VISOR_MAX_INTENTOS:
                contexto['bloqueado'] = True
                return render(request, 'pacientes/visor_gate.html', contexto)
            ultimos = (request.POST.get('dpi_ultimos') or '').strip()
            if ultimos and ultimos == (paciente.dpi or '')[-4:]:
                request.session[clave_ok] = True
                request.session.pop(clave_intentos, None)
                return redirect(f'{reverse("visor_estudio")}?{qs}')
            request.session[clave_intentos] = intentos + 1
            contexto['error'] = 'Los 4 dígitos no coinciden con el DPI registrado.'
            contexto['intentos_restantes'] = VISOR_MAX_INTENTOS - (intentos + 1)
            return render(request, 'pacientes/visor_gate.html', contexto)

        contexto['bloqueado'] = intentos >= VISOR_MAX_INTENTOS
        return render(request, 'pacientes/visor_gate.html', contexto)

    imagenes = list(
        orden.imagenes.filter(seleccionada=True).exclude(archivo='').order_by('subida_en')
    )
    informes = list(orden.informes.select_related('tipo_estudio').all())
    return render(request, 'pacientes/visor_estudio.html', {
        'orden': orden,
        'cita': orden.cita,
        'paciente': paciente,
        'imagenes': imagenes,
        'tab': 'report' if request.GET.get('tab') == 'report' else 'images',
        'informes': informes,
        'tiene_pdf': any(i.archivo for i in informes),
        'tiene_dicom': any(img.archivo_original for img in imagenes),
        'edad': paciente.edad_en(orden.cita.fecha),
    })


def _visor_orden_autorizada(request, orden_id):
    if request.session.get(f'visor_ok_{orden_id}') is not True:
        raise Http404
    return get_object_or_404(
        OrdenTrabajo, id=orden_id, resultados_enviados_en__isnull=False,
    )


def visor_imagen(request, orden_id, imagen_id):
    orden = _visor_orden_autorizada(request, orden_id)
    imagen = get_object_or_404(
        orden.imagenes.filter(seleccionada=True).exclude(archivo=''), id=imagen_id,
    )
    descargar = request.GET.get('descargar') == '1'
    return FileResponse(
        imagen.archivo.open('rb'),
        as_attachment=descargar,
        filename=(
            f'{orden.cita.paciente.apellido}_{orden.cita.fecha}_{imagen_id}.jpg'
            if descargar else None
        ),
    )


def visor_jpg(request, orden_id):
    """Zip con las imágenes JPG seleccionadas, para descargar desde el visor
    (botón "Descargar JPG")."""
    orden = _visor_orden_autorizada(request, orden_id)
    imagenes = list(orden.imagenes.filter(seleccionada=True).exclude(archivo=''))
    if not imagenes:
        raise Http404

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for n, imagen in enumerate(imagenes, start=1):
            with imagen.archivo.open('rb') as fh:
                zf.writestr(f'imagen_{n:02d}.jpg', fh.read())
    buffer.seek(0)
    respuesta = HttpResponse(buffer.getvalue(), content_type='application/zip')
    respuesta['Content-Disposition'] = (
        f'attachment; filename="imagenes_{orden.cita.paciente.dpi}.zip"'
    )
    return respuesta


@xframe_options_sameorigin
def visor_informe_pdf(request, orden_id, informe_id):
    orden = _visor_orden_autorizada(request, orden_id)
    informe = get_object_or_404(InformeEstudio, id=informe_id, orden=orden)
    if not informe.archivo:
        raise Http404
    descargar = request.GET.get('descargar') == '1'
    return FileResponse(
        informe.archivo.open('rb'),
        as_attachment=descargar,
        content_type='application/pdf',
        filename=f'informe_{informe.tipo_estudio.nombre}_{orden.cita.paciente.apellido}_{orden.cita.fecha}.pdf',
    )


def visor_dicom(request, orden_id):
    """Zip con los DICOM originales de las imágenes seleccionadas, para que
    el paciente los baje desde el visor (botón "Descargar DICOM")."""
    orden = _visor_orden_autorizada(request, orden_id)
    imagenes = [
        img for img in orden.imagenes.filter(seleccionada=True) if img.archivo_original
    ]
    if not imagenes:
        raise Http404

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        usados = set()
        for imagen in imagenes:
            nombre = os.path.basename(imagen.archivo_original.name)
            base, ext = os.path.splitext(nombre)
            candidato, i = nombre, 1
            while candidato in usados:
                candidato, i = f'{base}_{i}{ext}', i + 1
            usados.add(candidato)
            with imagen.archivo_original.open('rb') as fh:
                zf.writestr(candidato, fh.read())
    buffer.seek(0)
    respuesta = HttpResponse(buffer.getvalue(), content_type='application/zip')
    respuesta['Content-Disposition'] = (
        f'attachment; filename="estudio_{orden.cita.paciente.dpi}.zip"'
    )
    return respuesta
