"""Turnos de la sala de espera: tickets, pantalla pública y emergencias.
"""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts import sucursales
from accounts.models import Bitacora
from clinica.validators import avisar_si_correo_no_existe

from ..forms import ProcesarTicketForm, RegistrarTicketForm
from ..models import Cita, Cobro, OrdenTrabajo, Ticket, TipoEstudio
from .avisos import _notificar_orden_pendiente
from .citas import _sucursal_para_operar
from .pacientes import obtener_o_actualizar_paciente
from .permisos import es_recepcionista


# Registrar Ticket: check-in de pacientes que llegan a Emergencia IGSS sin
# cita agendada. Genera un turno numerado (ver Ticket.save) para la fila de
# atención. Siempre entra como prioridad "Urgente": es la única forma de
# obtener esa prioridad en la Pantalla de turnos (COEX/Privado son siempre
# "Normal", ver _crear_ticket_de_turno).
@login_required
@user_passes_test(es_recepcionista)
def registrar_ticket_emergencia(request):
    volver_url = reverse('pantalla_placeholder', kwargs={'clave': 'emergencia_igss'})
    sucursal = _sucursal_para_operar(request)
    if sucursal is None:
        return redirect('dashboard')

    if request.method == 'POST':
        form = RegistrarTicketForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            paciente = obtener_o_actualizar_paciente(cd)
            ticket = Ticket.objects.create(
                paciente=paciente,
                sucursal=sucursal,
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

    tickets_del_dia = sucursales.filtrar(Ticket.del_dia(fecha), request).select_related(
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


def _sucursal_sala_espera(request):
    """La pantalla de la sala de espera es pública (la TV no inicia sesión): la
    sucursal va en la URL, ?sucursal=<id>. Sin ese dato, la principal."""
    from accounts.models import Sucursal
    try:
        sucursal = Sucursal.objects.filter(id=int(request.GET.get('sucursal', ''))).first()
    except ValueError:
        sucursal = None
    return sucursal or Sucursal.objects.filter(es_principal=True).first()


def _turno_actual_sala_espera(hoy, sucursal):
    """El último turno llamado (marcado atendido) hoy en la sucursal, o None."""
    return (
        Ticket.del_dia(hoy)
        .filter(sucursal=sucursal)
        .select_related('paciente', 'cita__radiologo', 'cita__tipo_estudio')
        .filter(estado=Ticket.ESTADO_ATENDIDO)
        .order_by('-atendido_en')
        .first()
    )


def _proximos_sala_espera(hoy, sucursal):
    return (
        Ticket.del_dia(hoy)
        .filter(estado=Ticket.ESTADO_EN_ESPERA, sucursal=sucursal)
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
    sucursal = _sucursal_sala_espera(request)
    actual = _turno_actual_sala_espera(hoy, sucursal)
    return render(request, 'pacientes/pantalla_sala_espera.html', {
        'actual': _actual_sala_espera_dict(actual),
        'proximos': _proximos_sala_espera(hoy, sucursal),
        'hoy': hoy,
        'sucursal': sucursal,
    })


def estado_sala_espera(request):
    """JSON con el estado de la sala de espera, para que la pantalla del
    televisor se refresque sola sin recargar toda la página. Público, igual
    que pantalla_sala_espera."""
    hoy = timezone.localdate()
    sucursal = _sucursal_sala_espera(request)
    return JsonResponse({
        'actual': _actual_sala_espera_dict(_turno_actual_sala_espera(hoy, sucursal)),
        'proximos': [{'turno': t.turno} for t in _proximos_sala_espera(hoy, sucursal)],
    })


@login_required
@user_passes_test(es_recepcionista)
@require_POST
def avanzar_turno(request, ticket_id):
    """Marca este ticket como atendido (desaparece de la Pantalla de turnos)
    y de paso el siguiente en la cola pasa a ser el turno actual."""
    ticket = get_object_or_404(sucursales.permitidas(Ticket.objects, request.user), id=ticket_id, estado=Ticket.ESTADO_EN_ESPERA)
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
    ticket = get_object_or_404(sucursales.permitidas(Ticket.objects, request.user), id=ticket_id, estado=Ticket.ESTADO_EN_ESPERA)
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
        sucursales.permitidas(Ticket.objects.select_related('paciente', 'cita'), request.user),
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
def reagendar_desde_turno(request, ticket_id):
    """El paciente ya había marcado llegada (tiene turno en la fila) pero
    no se va a poder atender hoy -- se fue, tuvo una emergencia, etc. -- y
    quiere que se le reagende para otro día, sin esperar a que pase su
    hora. Saca el turno de la fila, marca la cita como ausente (mismo
    estado que ya usa el flujo normal de reagendar) y manda directo al
    calendario a elegir la nueva fecha/hora."""
    ticket = get_object_or_404(
        sucursales.permitidas(Ticket.objects.select_related('paciente', 'cita'), request.user),
        id=ticket_id, estado=Ticket.ESTADO_EN_ESPERA,
    )
    cita = ticket.cita
    if cita is None or not cita.se_puede_eliminar:
        messages.error(
            request,
            'Este turno ya no se puede reagendar: el estudio ya entró al flujo de trabajo '
            '(técnico/caja). Si hace falta, gestionalo desde "Procesar citas".',
        )
        return redirect('pantalla_turnos')

    ticket.estado = Ticket.ESTADO_AUSENTE
    ticket.save(update_fields=['estado'])

    cita.hora_llegada = None
    cita.estado = Cita.ESTADO_AUSENTE
    cita.save(update_fields=['hora_llegada', 'estado'])

    Bitacora.registrar(
        request=request, usuario=request.user,
        accion=Bitacora.ACCION_REAGENDAR_DESDE_TURNO,
        descripcion=(
            f'Sacó de la fila de espera a {ticket.paciente} (turno {ticket.turno}) '
            f'para reagendar la cita #{cita.id}.'
        ),
    )
    return redirect(f"{reverse(f'calendario_{cita.convenio}')}?reagendar={cita.id}")


@login_required
@user_passes_test(es_recepcionista)
@require_POST
def procesar_turno(request, ticket_id):
    """Genera de una vez la orden de trabajo del turno y la manda al técnico.
    Para los turnos de COEX/Privado usa la cita que ya existe; los de
    Emergencia IGSS (sin cita) van a la pantalla que pide el tipo de estudio."""
    ticket = get_object_or_404(sucursales.permitidas(Ticket.objects, request.user), id=ticket_id, estado=Ticket.ESTADO_EN_ESPERA)

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
    ticket = get_object_or_404(sucursales.permitidas(Ticket.objects, request.user), id=ticket_id, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS)
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
                codigo_igss=form.cleaned_data['codigo_igss'],
                medico_tratante=form.cleaned_data['medico_tratante'],
                notas=ticket.motivo,
                creada_por=request.user,
                sucursal=ticket.sucursal,
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
