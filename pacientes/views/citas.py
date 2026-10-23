"""Agenda: calendario de horarios, agendar citas (COEX, Emergencia IGSS y privado),
confirmación de solicitudes por el radiólogo, llegada del paciente, generación de la orden de trabajo,
reagendar, ausencias y eliminación de citas.
"""
import datetime

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts import sucursales
from accounts.models import Bitacora, Usuario
from clinica.validators import avisar_si_correo_no_existe

from ..forms import AgendarCitaForm, AgendarCitaPrivadoForm, GenerarOrdenForm
from ..horarios import (
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
from ..models import Cita, Cobro, Notificacion, OrdenTrabajo, ReporteDiario, Ticket
from .avisos import (
    _notificar_cita_asignada,
    _notificar_cita_confirmada,
    _notificar_cita_rechazada,
    _notificar_orden_pendiente,
)
from .pacientes import obtener_o_actualizar_paciente
from .permisos import es_radiologo, es_recepcionista


# Cuántas citas de emergencia (agendadas encima de otra ya existente) se
# permiten como máximo por día, para no saturar a la radióloga.
MAXIMO_EMERGENCIAS_POR_DIA = 5

# Etiqueta corta del convenio para mostrar en las celdas del calendario.
ETIQUETA_CONVENIO_CORTA = {
    Cita.CONVENIO_COEX: 'COEX',
    Cita.CONVENIO_PRIVADO: 'Privado',
    Cita.CONVENIO_EMERGENCIA_IGSS: 'Emerg. IGSS',
}


@login_required
@user_passes_test(es_recepcionista)
def seleccionar_horario(request, convenio):
    convenio_nombre = dict(Cita.CONVENIO_CHOICES).get(convenio, convenio)
    sucursal = _sucursal_para_operar(request)
    if sucursal is None:
        return redirect('dashboard')

    reagendar_cita = None
    reagendar_id = request.GET.get('reagendar')
    if reagendar_id:
        reagendar_cita = get_object_or_404(sucursales.permitidas(Cita.objects, request.user), id=reagendar_id, convenio=convenio)

    hoy = datetime.date.today()
    semana_param = parse_date(request.GET.get('semana', ''))
    inicio = inicio_semana(semana_param or hoy)
    dias = [inicio + datetime.timedelta(days=i) for i in range(len(DIAS_SEMANA))]

    citas_semana = (
        Cita.objects.filter(fecha__gte=dias[0], fecha__lte=dias[-1], sucursal=sucursal)
        .exclude(estado=Cita.ESTADO_RECHAZADA)
        .select_related('tipo_estudio', 'paciente', 'radiologo', 'orden_trabajo', 'cobro')
    )
    if reagendar_cita:
        citas_semana = citas_semana.exclude(id=reagendar_cita.id)

    # Selector de radiólogo: si se elige uno, el calendario muestra solo la
    # agenda de ESE radiólogo (para ver si tiene un hueco cuando otro está
    # lleno). Sin elegir, se ve la agenda de toda la clínica.
    radiologos = list(
        sucursales.de_usuarios(Usuario.objects.filter(rol=Usuario.ROL_MEDICO_RADIOLOGO, is_active=True), sucursal)
        .order_by('first_name', 'last_name', 'username')
    )
    radiologo_id = request.GET.get('radiologo') or ''
    radiologo_seleccionado = next(
        (r for r in radiologos if str(r.id) == radiologo_id), None,
    )
    if radiologo_seleccionado:
        citas_semana = citas_semana.filter(radiologo=radiologo_seleccionado)

    # El calendario es único para toda la sucursal: un turno ocupado por
    # cualquier convenio (COEX / Privado / Emergencia IGSS) se ve ocupado en
    # los tres. Cada sucursal tiene su propia agenda. Se guarda además la lista de citas de cada franja para poder
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


def _sucursal_para_operar(request):
    """Sucursal donde se agenda / registra ahora (la activa del usuario). None si el
    administrador está en "Todas las sucursales": en ese caso se le pide elegir una."""
    sucursal = sucursales.sucursal_activa(request)
    if sucursal is None:
        messages.info(
            request,
            'Elija una sucursal en la barra lateral para trabajar con su agenda, citas y turnos.',
        )
    return sucursal


def _hay_estudio_duplicado(*, dpi, tipo_estudio, fecha, hora):
    """Evita agendar el mismo estudio dos veces al mismo paciente en el
    mismo horario, aunque se intente desde otro convenio."""
    return Cita.objects.filter(
        paciente__dpi=dpi,
        tipo_estudio=tipo_estudio,
        fecha=fecha,
        hora=hora,
    ).exclude(estado=Cita.ESTADO_RECHAZADA).exists()


def _hay_conflicto_horario(fecha_dt, hora_time, duracion_minutos, sucursal):
    """¿El horario dado se cruza con alguna cita ya existente ese día en esa
    sucursal? (cada sucursal tiene su propia agenda; no cuenta las rechazadas)."""
    if not fecha_dt or not hora_time:
        return False
    ocupados = [
        rango_ocupado_por(c.fecha, c.hora, c.tipo_estudio.duracion_minutos)
        for c in Cita.objects.filter(fecha=fecha_dt, sucursal=sucursal)
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
    sucursal = _sucursal_para_operar(request)
    if sucursal is None:
        return redirect('dashboard')

    datos = request.POST if request.method == 'POST' else request.GET
    fecha = datos.get('fecha')
    hora = datos.get('hora')
    if not fecha or not hora:
        return redirect(calendario_url)

    if request.method == 'POST':
        form = AgendarCitaForm(request.POST, convenio=convenio, sucursal=sucursal)
    else:
        inicial = {'fecha': fecha, 'hora': hora}
        if request.GET.get('radiologo'):
            inicial['radiologo'] = request.GET['radiologo']
        form = AgendarCitaForm(initial=inicial, convenio=convenio, sucursal=sucursal)
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
    hay_conflicto = _hay_conflicto_horario(fecha_dt, hora_time, PASO_MINUTOS, sucursal)

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

        hay_conflicto = _hay_conflicto_horario(cd['fecha'], cd['hora'], cd['tipo_estudio'].duracion_minutos, sucursal)

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
                    fecha=cd['fecha'], es_emergencia_forzada=True, sucursal=sucursal,
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
                codigo_igss=cd['codigo_igss'],
                medico_tratante=cd['medico_tratante'],
                fecha_sugerida=cd['fecha'],
                hora_sugerida=cd['hora'],
                notas=cd['notas'],
                creada_por=request.user,
                es_emergencia_forzada=hay_conflicto,
                sucursal=sucursal,
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
    sucursal = _sucursal_para_operar(request)
    if sucursal is None:
        return redirect('dashboard')

    datos = request.POST if request.method == 'POST' else request.GET
    fecha_inicial = datos.get('fecha')
    hora_inicial = datos.get('hora')

    if request.method == 'POST':
        form = AgendarCitaPrivadoForm(request.POST, sucursal=sucursal)
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
                cd['fecha'], cd['hora'], cd['tipo_estudio'].duracion_minutos, sucursal,
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
                medico_tratante=cd.get('medico_tratante'),
                fecha_sugerida=cd['fecha'],
                hora_sugerida=cd['hora'],
                notas=cd['motivo'],
                creada_por=request.user,
                revisada_por=request.user,
                revisada_en=timezone.now(),
                sucursal=sucursal,
            )
            ReporteDiario.de_cita(cita)
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
        form = AgendarCitaPrivadoForm(initial=inicial, sucursal=sucursal)
        if fecha_inicial and hora_inicial:
            try:
                hora_dt = datetime.datetime.strptime(hora_inicial, '%H:%M').time()
            except ValueError:
                hora_dt = None
            if hora_dt and _hay_conflicto_horario(parse_date(fecha_inicial), hora_dt, PASO_MINUTOS, sucursal):
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
        sucursales.filtrar(Cita.objects.filter(convenio=convenio, fecha=fecha), request)
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
    marcarse como llegada (COEX/Privado). Si por algún motivo ya existiera un
    ticket EN CURSO para esta cita (doble clic, etc.) no crea uno duplicado
    -- pero uno viejo ya ausente/atendido (p.ej. porque antes se usó
    "Reagendar" desde la Pantalla de turnos, que deja el ticket anterior en
    ESTADO_AUSENTE sin tocar la cita) no cuenta: esa cita ya puede tener un
    turno nuevo cuando el paciente vuelve a llegar."""
    ticket_existente = Ticket.objects.filter(
        cita=cita, estado__in=(Ticket.ESTADO_EN_ESPERA, Ticket.ESTADO_EN_ATENCION),
    ).first()
    if ticket_existente:
        return ticket_existente
    ticket = Ticket.objects.create(
        paciente=cita.paciente,
        cita=cita,
        sucursal=cita.sucursal,
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
    cita = get_object_or_404(sucursales.permitidas(Cita.objects, request.user), id=cita_id, convenio=convenio)
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
            messages.success(request, f'Se registró la llegada de {cita.paciente} — turno {ticket.turno}.')
        else:
            messages.success(request, f'Se registró la llegada de {cita.paciente}.')
    return redirect(f'{reverse(f"procesar_citas_{convenio}")}?fecha={cita.fecha}')


@login_required
@user_passes_test(es_recepcionista)
def generar_orden(request, convenio, cita_id):
    cita = get_object_or_404(sucursales.permitidas(Cita.objects, request.user), id=cita_id, convenio=convenio)
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
@user_passes_test(es_radiologo)
def solicitudes_pendientes(request):
    busqueda = (request.GET.get('q') or '').strip()
    convenio = (request.GET.get('convenio') or '').strip()
    citas = (
        sucursales.filtrar(Cita.objects.filter(estado=Cita.ESTADO_PENDIENTE, radiologo=request.user), request)
        .select_related('paciente', 'tipo_estudio')
        .order_by('fecha_sugerida', 'hora_sugerida')
    )
    if busqueda:
        citas = citas.filter(
            Q(paciente__nombre__icontains=busqueda)
            | Q(paciente__apellido__icontains=busqueda)
            | Q(paciente__dpi__icontains=busqueda)
            | Q(paciente__telefono__icontains=busqueda)
            | Q(tipo_estudio__nombre__icontains=busqueda)
        )
    if convenio in dict(Cita.CONVENIO_CHOICES):
        citas = citas.filter(convenio=convenio)
    return render(request, 'pacientes/solicitudes_pendientes.html', {
        'citas': citas,
        'busqueda': busqueda,
        'convenio': convenio,
        'convenios': Cita.CONVENIO_CHOICES,
    })


@login_required
@user_passes_test(es_radiologo)
def revisar_solicitud(request, cita_id):
    cita = get_object_or_404(
        sucursales.permitidas(Cita.objects, request.user),
        id=cita_id, estado=Cita.ESTADO_PENDIENTE, radiologo=request.user,
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
        ReporteDiario.de_cita(cita)
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
    cita = get_object_or_404(sucursales.permitidas(Cita.objects, request.user), id=cita_id, convenio=convenio)
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
    cita = get_object_or_404(sucursales.permitidas(Cita.objects, request.user), id=cita_id, convenio=convenio)
    calendario_url = reverse(f'calendario_{convenio}')

    if cita.estado not in (Cita.ESTADO_AUSENTE, Cita.ESTADO_AGENDADA):
        messages.error(request, 'Solo se pueden reagendar citas agendadas o marcadas como ausente.')
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
            for c in Cita.objects.filter(fecha=fecha, sucursal=cita.sucursal)
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
        ReporteDiario.de_cita(cita)
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
        sucursales.permitidas(Cita.objects.select_related('paciente', 'tipo_estudio', 'radiologo', 'orden_trabajo', 'cobro'), request.user),
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
        fecha=cita.fecha, convenio=cita.convenio, sucursal=cita.sucursal, estado=ReporteDiario.ESTADO_ENVIADO,
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
