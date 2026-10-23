"""Creación de notificaciones internas (la campanita) para los pasos del flujo.

Cada ``_notificar_*`` se llama desde la vista que cambia el estado de la cita u
orden y avisa al rol que tiene que actuar después (recepción, técnico,
radiólogo, caja). Las vistas que listan/marcan notificaciones están en
``notificaciones.py``.
"""
from django.db.models import Q
from django.urls import NoReverseMatch, reverse

from accounts import sucursales
from accounts.models import Usuario

from ..models import Cita, Notificacion
from .permisos import es_caja


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
    tecnicos = sucursales.de_usuarios(Usuario.objects.filter(rol=Usuario.ROL_TECNICO_IMAGENES, is_active=True), cita.sucursal)
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
    usuarios = sucursales.de_usuarios(Usuario.objects.filter(is_active=True).filter(
        Q(rol=Usuario.ROL_RECEPCIONISTA) | Q(puede_operar_caja=True)
    ), cita.sucursal).distinct()
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
    recepcionistas = sucursales.de_usuarios(Usuario.objects.filter(rol=Usuario.ROL_RECEPCIONISTA, is_active=True), cita.sucursal)
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
    tecnicos = sucursales.de_usuarios(Usuario.objects.filter(rol=Usuario.ROL_TECNICO_IMAGENES, is_active=True), orden.cita.sucursal)
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
        radiologos = sucursales.de_usuarios(Usuario.objects.filter(rol=Usuario.ROL_MEDICO_RADIOLOGO, is_active=True), cita.sucursal)
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
    recepcionistas = sucursales.de_usuarios(Usuario.objects.filter(rol=Usuario.ROL_RECEPCIONISTA, is_active=True), cita.sucursal)
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
