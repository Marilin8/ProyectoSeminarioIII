"""Sucursal activa del usuario.

Cada usuario trabaja en una o varias sucursales (Usuario.sucursales). La que tiene
"activa" se guarda en la sesión y la elige desde la barra lateral si tiene más de una.
El administrador además puede elegir "Todas las sucursales" (None) para ver todo junto.

Etapa 1: solo se guarda y se muestra la elección. Las pantallas de operación, los
reportes y las gráficas la usarán para filtrar en las etapas siguientes
(ver sucursal_activa()).
"""
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
    viendo todas (o un usuario sin ninguna sucursal asignada)."""
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
    return opciones[0] if opciones else None


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
