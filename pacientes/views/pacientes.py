"""Búsqueda, historial y datos de contacto de pacientes.

Incluye ``obtener_o_actualizar_paciente`` (lo usan los formularios de agendar
cita para reutilizar al paciente por DPI) y los endpoints JSON que autocompletan
el formulario de recepción.
"""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import sucursales
from accounts.models import Usuario
from clinica.validators import avisar_si_correo_no_existe

from ..forms import CompletarDatosPacienteForm, EditarContactoPacienteForm
from ..models import Cita, Cobro, Notificacion, OrdenPago, OrdenTrabajo, Paciente, TipoEstudio
from .avisos import _notificar_datos_pendientes_si_corresponde
from .permisos import es_recepcionista


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
def buscar_paciente_por_telefono(request):
    """Avisa si el teléfono ingresado ya está registrado a nombre de OTRO
    paciente, para no duplicarlo por error al escribirlo a mano. No bloquea
    nada (a diferencia del DPI, que es único): es normal que varios
    pacientes -ej. familiares- compartan un mismo número de contacto, así
    que solo se informa de quién es."""
    telefono = (request.GET.get('telefono') or '').strip()
    excluir_dpi = (request.GET.get('excluir_dpi') or '').strip()
    if not telefono:
        return JsonResponse({'encontrado': False})
    paciente = Paciente.objects.filter(telefono=telefono).exclude(dpi=excluir_dpi).first()
    if not paciente:
        return JsonResponse({'encontrado': False})
    return JsonResponse({
        'encontrado': True,
        'nombre': paciente.nombre,
        'apellido': paciente.apellido,
        'dpi': paciente.dpi,
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
    sucursal = sucursales.sucursal_activa(request)
    if sucursal is not None:
        radiologos = sucursales.de_usuarios(radiologos, sucursal)
    return JsonResponse({
        'radiologos': [
            {'id': r.id, 'texto': r.get_full_name() or r.username} for r in radiologos
        ],
    })


ESTADOS_HISTORIAL = (Cita.ESTADO_EN_PROCESO, Cita.ESTADO_PROCESADA)


@login_required
@user_passes_test(es_recepcionista)
def historial_pacientes(request):
    """Listado de pacientes con al menos un estudio en proceso o ya
    realizado (informe entregado), con búsqueda por nombre/apellido, DPI o
    N° de expediente y filtros por convenio, fecha y tipo de estudio. Los
    estudios en proceso se muestran con sus etiquetas de qué falta (pago,
    imágenes, informe) para que recepción pueda seguirles el rastro sin
    tener que esperar a que se completen. Los que todavía tienen datos
    pendientes (sexo/teléfono/fecha de nacimiento) van primero, con un
    botón para completarlos; a los demás se les muestra de qué
    convenio(s) son sus estudios (COEX, Privado, Emergencia IGSS)."""
    busqueda = (request.GET.get('q') or '').strip()
    filtro_convenio = (request.GET.get('convenio') or '').strip()
    filtro_fecha = (request.GET.get('fecha') or '').strip()
    filtro_tipo_estudio = (request.GET.get('tipo_estudio') or '').strip()
    filtro_estado_pago = (request.GET.get('estado_pago') or '').strip()
    filtro_agrupacion = (request.GET.get('agrupacion') or '').strip()

    citas_procesadas = sucursales.filtrar(Cita.objects.filter(estado__in=ESTADOS_HISTORIAL), request)
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
            Cita.objects.filter(paciente__in=pacientes, estado__in=ESTADOS_HISTORIAL)
            .order_by().values_list('paciente_id', 'convenio').distinct()
        )
        for paciente_id, convenio in filas:
            convenios_por_paciente.setdefault(paciente_id, []).append(
                convenios_choices.get(convenio, convenio)
            )

    # Último estudio de cada paciente (entre los que pasan los filtros), para mostrar
    # primero a quien se le hizo un estudio más recientemente.
    ultimo_estudio = {}
    for paciente_id, fecha, hora in citas_procesadas.order_by().values_list('paciente_id', 'fecha', 'hora'):
        momento = (fecha, hora)
        if paciente_id not in ultimo_estudio or momento > ultimo_estudio[paciente_id]:
            ultimo_estudio[paciente_id] = momento

    for paciente in pacientes:
        paciente.datos_pendientes = paciente.campos_pendientes()
        paciente.convenios_estudios = sorted(convenios_por_paciente.get(paciente.id, []))
        paciente.ultimo_estudio = ultimo_estudio.get(paciente.id)

    # El último paciente atendido primero (los datos pendientes siguen marcados en
    # cada tarjeta); a igual fecha y hora, por nombre.
    pacientes.sort(key=lambda p: (p.nombre, p.apellido))
    pacientes.sort(
        key=lambda p: p.ultimo_estudio or (datetime.date.min, datetime.time.min), reverse=True,
    )

    contexto = {
        'pacientes': pacientes,
        'busqueda': busqueda,
        'filtro_convenio': filtro_convenio,
        'filtro_fecha': filtro_fecha,
        'filtro_tipo_estudio': filtro_tipo_estudio,
        'filtro_estado_pago': filtro_estado_pago,
        'filtro_agrupacion': filtro_agrupacion,
        'tipos_estudio': TipoEstudio.objects.filter(
            id__in=Cita.objects.filter(estado__in=ESTADOS_HISTORIAL).values('tipo_estudio_id')
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
    """Estudios en proceso o ya realizados de un paciente, del más
    reciente al más antiguo. Los que todavía están en proceso se muestran
    con etiquetas de qué les falta (pago, imágenes, informe)."""
    paciente = get_object_or_404(Paciente, id=paciente_id)
    filtro_estado_pago = (request.GET.get('estado_pago') or '').strip()
    filtro_agrupacion = (request.GET.get('agrupacion') or '').strip()
    citas = (
        sucursales.permitidas(Cita.objects.filter(paciente=paciente, estado__in=ESTADOS_HISTORIAL), request.user)
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


@login_required
@user_passes_test(es_recepcionista)
@require_POST
def editar_contacto_paciente(request, paciente_id):
    """Corrige el teléfono y/o el correo del paciente desde "Estudios
    realizados", sin salir de esa pantalla -- para el caso de un correo mal
    escrito (o que faltaba) que hizo fallar el envío automático o manual.
    No envía nada por sí sola: el botón de enviar/reenviar sigue aparte,
    para que quien corrige revise antes de mandar."""
    paciente = get_object_or_404(Paciente, id=paciente_id)
    form = EditarContactoPacienteForm(request.POST)
    if form.is_valid():
        cd = form.cleaned_data
        cambiados = [
            campo for campo in ('telefono', 'correo')
            if cd[campo] and cd[campo] != (getattr(paciente, campo) or '')
        ]
        for campo in cambiados:
            setattr(paciente, campo, cd[campo])
        if cambiados:
            paciente.save(update_fields=cambiados)
            messages.success(request, f'Datos de contacto de {paciente} actualizados.')
        else:
            messages.info(request, 'No se cargó ningún dato nuevo.')
    else:
        avisar_si_correo_no_existe(request, form)
        for campo, errores in form.errors.items():
            for error in errores:
                messages.error(request, error)
    return redirect('historial_paciente', paciente_id=paciente.id)


@login_required
@user_passes_test(es_recepcionista)
def ver_estudio_historial(request, cita_id):
    """Vista de solo lectura de un estudio ya realizado: imágenes e
    informe, tal como quedaron al terminar el proceso."""
    cita = get_object_or_404(sucursales.permitidas(Cita.objects, request.user), id=cita_id, estado=Cita.ESTADO_PROCESADA)
    orden = get_object_or_404(sucursales.permitidas(OrdenTrabajo.objects, request.user, 'cita__sucursal'), cita=cita)
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
