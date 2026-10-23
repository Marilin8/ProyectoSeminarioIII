"""Endpoints de la campanita de notificaciones (listar y marcar como leídas).
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone

from accounts import sucursales

from ..models import Notificacion


MAX_NOTIFICACIONES_EN_CAMPANITA = 20


def _notificaciones_de(request):
    """Avisos del usuario de la sucursal en la que está trabajando ahora: quien está
    en varias sucursales solo ve los de la activa. Los avisos que no son de una cita
    (p. ej. reportes enviados) se ven siempre; el administrador con "Todas las
    sucursales" ve todos."""
    avisos = request.user.notificaciones.all()
    activa = sucursales.sucursal_activa(request)
    if activa is not None:
        avisos = avisos.filter(Q(cita__isnull=True) | Q(cita__sucursal=activa))
    return avisos


@login_required
def notificaciones_pendientes(request):
    """Endpoint que la campanita de notificaciones consulta cada cierto
    tiempo (ver includes/notificaciones.html) para saber si hay avisos
    nuevos y hacer sonar el aviso."""
    pendientes = _notificaciones_de(request).filter(leida=False)
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
        # Solo las que está viendo (las de su sucursal activa).
        _notificaciones_de(request).filter(leida=False).exclude(
            tipo=Notificacion.TIPO_DATOS_PACIENTE_PENDIENTES,
        ).update(leida=True)
    return JsonResponse({'ok': True})
