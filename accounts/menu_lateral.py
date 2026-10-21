"""Menú desplegable de la barra lateral.

Arma, para el usuario que inició sesión, un árbol con las mismas pantallas que ve en
el menú principal (ver pantallas.pantallas_de), más los accesos propios del
administrador. Las entradas con "submenu" se abren como una columna a la derecha
de la barra (ver templates/includes/menu_lateral.html).
"""
from django.urls import NoReverseMatch, reverse

from .pantallas import pantallas_de

# Ícono (id del <symbol> en includes/icons.html) por url_name o clave.
ICONOS = {
    'estado_clinica': 'i-activity',
    'crear_usuario': 'i-user',
    'lista_sucursales': 'i-map-pin',
    'usuarios_activos': 'i-users',
    'lista_estudios': 'i-file-medical',
    'lista_modalidades': 'i-layers',
    'lista_combos': 'i-grid',
    'lista_medicos_tratantes': 'i-heart',
    'bitacora': 'i-list',
    'respaldos': 'i-shield',
    'reportes_diarios': 'i-file-text',
    'informe_anual': 'i-bar-chart',
    'coex': 'i-calendar',
    'privado': 'i-calendar',
    'emergencia_igss': 'i-alert-circle',
    'pantalla_turnos': 'i-clock',
    'estudios_por_corregir': 'i-edit',
    'historial_pacientes': 'i-folder',
    'ordenes_pendientes': 'i-camera',
    'solicitudes_pendientes': 'i-clipboard',
    'citas_procesadas': 'i-file-medical',
    'pagos_pendientes': 'i-check-circle',
    'pagos_pendientes_igss': 'i-check-circle',
    'paneles': 'i-bar-chart',
    'planilla': 'i-file-text',
}


def _url(nombre):
    try:
        return reverse(nombre)
    except NoReverseMatch:
        return None


def _nodo(pantalla, ruta_actual, nivel=0):
    clave = pantalla.get('clave') or pantalla.get('url_name')
    hijos = [
        n for n in (_nodo(h, ruta_actual, nivel + 1) for h in pantalla.get('submenu', []))
        if n is not None
    ]
    if pantalla.get('submenu'):
        if not hijos:
            return None
        url = None
    else:
        url = _url(pantalla['url_name']) if pantalla.get('url_name') else None
        if url is None:
            return None
    # Las rutas de un solo nivel (/dashboard/, /respaldos/) solo se marcan si coinciden
    # exacto; si no, /dashboard/ quedaría marcado también en /dashboard/finanzas/.
    activo = url is not None and (
        ruta_actual == url or (ruta_actual.startswith(url) and url.count('/') > 2)
    )
    activo = activo or any(h['activo'] for h in hijos)
    return {
        'id': f'menu-{clave}-{nivel}',
        'nombre': pantalla['nombre'],
        'url': url,
        'icono': ICONOS.get(clave, 'i-grid'),
        'hijos': hijos,
        'activo': activo,
    }


def arbol_para(usuario, ruta_actual=''):
    pantallas = list(pantallas_de(usuario))
    if usuario.is_superuser or usuario.tiene_rol(usuario.ROL_ADMINISTRADOR):
        pantallas = [
            {'nombre': 'Paneles', 'clave': 'paneles', 'submenu': [
                {'nombre': 'Estadísticas', 'url_name': 'dashboard'},
                {'nombre': 'Finanzas', 'url_name': 'panel_financiero'},
                {'nombre': 'Estado de la Clínica', 'url_name': 'estado_clinica'},
            ]},
        ] + [p for p in pantallas if p.get('url_name') != 'estado_clinica'] + [
            {'nombre': 'Planilla', 'url_name': 'planilla'},
        ]
    nodos = [_nodo(p, ruta_actual) for p in pantallas]
    return [n for n in nodos if n is not None]


def menu_lateral(request):
    """Procesador de contexto: `menu_lateral` en todas las plantillas."""
    usuario = getattr(request, 'user', None)
    if usuario is None or not usuario.is_authenticated:
        return {}
    return {'menu_lateral': arbol_para(usuario, request.path)}
