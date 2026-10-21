"""Sucursal activa del usuario.

Cada usuario trabaja en una o varias sucursales (Usuario.sucursales). La que tiene
"activa" se guarda en la sesión y la elige desde la barra lateral si tiene más de una.
El administrador además puede elegir "Todas las sucursales" (None) para ver todo junto.

Las pantallas de operación (agenda, citas, turnos, caja, órdenes, reportes diarios)
trabajan con la sucursal activa: `filtrar` para listados y `permitidas` para abrir un
registro por id (cualquiera de las sucursales del usuario).
"""
from django.db.models import Q

from .models import Sucursal, Usuario

CLAVE_SESION = 'sucursal_id'
TODAS = 'todas'


def ve_todas(usuario):
    return usuario.is_superuser or usuario.tiene_rol(Usuario.ROL_ADMINISTRADOR)


def disponibles(usuario):
    """Sucursales que el usuario puede elegir (el administrador: todas las activas)."""
    if ve_todas(usuario):
        return list(Sucursal.objects.filter(activa=True))
    return list(usuario.sucursales.filter(activa=True))


def sucursal_activa(request):
    """La Sucursal en la que trabaja ahora el usuario, o None si es el administrador
    viendo todas (o un usuario sin ninguna sucursal asignada). Se calcula una vez por
    request."""
    if not hasattr(request, '_sucursal_activa'):
        request._sucursal_activa = _calcular_activa(request)
    return request._sucursal_activa


def _calcular_activa(request):
    usuario = request.user
    opciones = disponibles(usuario)
    elegida = request.session.get(CLAVE_SESION)
    if elegida == TODAS and ve_todas(usuario):
        return None
    for sucursal in opciones:
        if sucursal.id == elegida:
            return sucursal
    if ve_todas(usuario):
        return None  # por defecto, el administrador ve todas
    if opciones:
        return opciones[0]
    # Usuario sin sucursal asignada: trabaja en la principal (igual que al crearlo
    # sin marcar ninguna).
    return Sucursal.objects.filter(es_principal=True).first()


def elegir(request, valor):
    """Guarda la elección del selector si es válida para el usuario."""
    usuario = request.user
    if valor == TODAS and ve_todas(usuario):
        request.session[CLAVE_SESION] = TODAS
        return
    try:
        sucursal_id = int(valor)
    except (TypeError, ValueError):
        return
    if any(s.id == sucursal_id for s in disponibles(usuario)):
        request.session[CLAVE_SESION] = sucursal_id
    request.__dict__.pop('_sucursal_activa', None)


def contexto(request):
    """Procesador de contexto: datos del selector de la barra lateral."""
    usuario = getattr(request, 'user', None)
    if usuario is None or not usuario.is_authenticated:
        return {}
    opciones = disponibles(usuario)
    activa = sucursal_activa(request)
    return {
        'sucursal_activa': activa,
        'sucursales_disponibles': opciones,
        'sucursal_ve_todas': ve_todas(usuario),
        # Solo hay algo que elegir si hay más de una opción.
        'sucursal_selector': len(opciones) + (1 if ve_todas(usuario) else 0) > 1,
    }


def filtrar(consulta, request, campo='sucursal'):
    """Listados de operación: solo lo de la sucursal activa. El administrador con
    "Todas las sucursales" ve todo; un usuario sin sucursal no ve nada."""
    activa = sucursal_activa(request)
    if activa is not None:
        return consulta.filter(**{campo: activa})
    if ve_todas(request.user):
        return consulta
    return consulta.none()


def permitidas(consulta, usuario, campo='sucursal'):
    """Para abrir un registro por id: debe ser de alguna sucursal del usuario (no
    necesariamente la activa, así no da 404 justo después de cambiar de sucursal)."""
    if ve_todas(usuario):
        return consulta
    return consulta.filter(**{f'{campo}__in': ids_de(usuario)}).distinct()


def ids_de(usuario):
    """Sucursales del usuario; sin ninguna asignada, la principal."""
    ids = list(usuario.sucursales.values_list('id', flat=True))
    return ids or list(Sucursal.objects.filter(es_principal=True).values_list('id', flat=True))


def q_trabajan_en(sucursal):
    """Q de usuarios que trabajan en `sucursal`. Los que no tienen ninguna asignada
    cuentan como de la principal."""
    condicion = Q(sucursales=sucursal)
    if sucursal.es_principal:
        condicion |= Q(sucursales__isnull=True)
    return condicion


def de_usuarios(usuarios, sucursal):
    """Usuarios (destinatarios de un aviso, radiólogos para elegir...) que trabajan
    en esa sucursal."""
    if sucursal is None:
        return usuarios
    return usuarios.filter(q_trabajan_en(sucursal)).distinct()
