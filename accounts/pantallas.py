from .models import Usuario

# Qué botones/pantallas ve cada rol al entrar al sistema. Cada entrada:
# - "nombre": texto del botón
# - "url_name": nombre de una URL real ya implementada (sin parámetros)
# - "clave": si no hay pantalla real todavía, usa esta clave para mostrar
#   un placeholder "en construcción" en /pantalla/<clave>/
# - "submenu": lista de sub-pantallas (mismo formato) que se muestran al
#   entrar a esta pantalla, en vez del placeholder
PANTALLAS_POR_ROL = {
    Usuario.ROL_ADMINISTRADOR: [
        {'nombre': 'Crear usuario', 'url_name': 'crear_usuario'},
        {
            'nombre': 'Usuarios activos',
            'clave': 'usuarios_activos',
            'submenu': [
                {'nombre': 'Radiólogos', 'url_name': 'lista_usuarios_radiologos'},
                {'nombre': 'Técnicos', 'url_name': 'lista_usuarios_tecnicos'},
                {'nombre': 'Secretarías', 'url_name': 'lista_usuarios_secretarias'},
            ],
        },
        {'nombre': 'Estudios', 'url_name': 'lista_estudios'},
        {'nombre': 'Modalidades', 'url_name': 'lista_modalidades'},
        {'nombre': 'Combos', 'url_name': 'lista_combos'},
        {'nombre': 'Médicos tratantes', 'url_name': 'lista_medicos_tratantes'},
        {'nombre': 'Bitácora del sistema', 'url_name': 'bitacora'},
        {
            'nombre': 'Reportes diarios',
            'clave': 'reportes_diarios',
            'submenu': [
                {'nombre': 'COEX', 'url_name': 'lista_reportes_diarios_coex'},
                {'nombre': 'Privado', 'url_name': 'lista_reportes_diarios_privado'},
                {'nombre': 'Emergencia IGSS', 'url_name': 'lista_reportes_diarios_emergencia_igss'},
            ],
        },
        {'nombre': 'Informe anual', 'url_name': 'informe_anual'},
    ],
    Usuario.ROL_RECEPCIONISTA: [
        {
            'nombre': 'COEX',
            'clave': 'coex',
            'submenu': [
                {'nombre': 'Agendar cita', 'url_name': 'calendario_coex'},
                {'nombre': 'Procesar cita', 'url_name': 'procesar_citas_coex'},
            ],
        },
        {
            'nombre': 'PRIVADO',
            'clave': 'privado',
            'submenu': [
                {'nombre': 'Agendar cita', 'url_name': 'calendario_privado'},
                {'nombre': 'Procesar cita', 'url_name': 'procesar_citas_privado'},
            ],
        },
        {
            'nombre': 'EMERGENCIA IGSS',
            'clave': 'emergencia_igss',
            'submenu': [
                {'nombre': 'Registrar Ticket', 'url_name': 'registrar_ticket_emergencia'},
            ],
        },
        {'nombre': 'Pantalla de turnos', 'url_name': 'pantalla_turnos'},
        {'nombre': 'Estudios por corregir', 'url_name': 'estudios_por_corregir'},
        {'nombre': 'Estudios realizados', 'url_name': 'historial_pacientes'},
        {
            'nombre': 'Reportes diarios',
            'clave': 'reportes_diarios',
            'submenu': [
                {'nombre': 'COEX', 'url_name': 'lista_reportes_diarios_coex'},
                {'nombre': 'Privado', 'url_name': 'lista_reportes_diarios_privado'},
                {'nombre': 'Emergencia IGSS', 'url_name': 'lista_reportes_diarios_emergencia_igss'},
            ],
        },
    ],
    Usuario.ROL_TECNICO_IMAGENES: [
        {'nombre': 'Órdenes pendientes', 'url_name': 'ordenes_pendientes'},
    ],
    Usuario.ROL_MEDICO_RADIOLOGO: [
        {'nombre': 'Solicitudes de citas', 'url_name': 'solicitudes_pendientes'},
        {'nombre': 'Citas procesadas', 'url_name': 'citas_procesadas'},
    ],
    Usuario.ROL_MEDICO_REMITENTE: [],
    Usuario.ROL_ADMINISTRADOR_FINANCIERO: [
        {
            'nombre': 'Reportes diarios',
            'clave': 'reportes_diarios',
            'submenu': [
                {'nombre': 'COEX', 'url_name': 'lista_reportes_diarios_coex'},
                {'nombre': 'Privado', 'url_name': 'lista_reportes_diarios_privado'},
                {'nombre': 'Emergencia IGSS', 'url_name': 'lista_reportes_diarios_emergencia_igss'},
            ],
        },
        {'nombre': 'Informe anual', 'url_name': 'informe_anual'},
    ],
}


def _identificador(pantalla):
    """Lo que identifica a una pantalla para no duplicarla en el panel: la
    'clave' si tiene submenú (placeholder /pantalla/<clave>/), si no el
    nombre de la URL real."""
    return pantalla.get('clave') or pantalla.get('url_name')


def pantallas_de(usuario):
    if usuario.is_superuser and usuario.rol != Usuario.ROL_ADMINISTRADOR:
        pantallas = list(PANTALLAS_POR_ROL[Usuario.ROL_ADMINISTRADOR])
    else:
        pantallas = list(PANTALLAS_POR_ROL.get(usuario.rol, []))
        # Roles adicionales (ver Usuario.tiene_rol/RolAdicional): un
        # técnico al que también se le habilitó el rol de radiólogo ve,
        # además de sus propios tiles, los de radiólogo -- sin duplicar
        # los que ya tenía en común (ej. "Reportes diarios").
        ya_vistas = {_identificador(p) for p in pantallas}
        for extra in usuario.roles_adicionales.all():
            for pantalla in PANTALLAS_POR_ROL.get(extra.rol, []):
                identificador = _identificador(pantalla)
                if identificador not in ya_vistas:
                    pantallas.append(pantalla)
                    ya_vistas.add(identificador)
    # Permiso aparte del rol (ver Usuario.puede_operar_caja): cualquier
    # usuario con este permiso ve la pantalla de Caja (y el acceso directo
    # a Pagos IGSS), sin duplicarlas si su rol ya las tuviera.
    ya_tiene_caja = any(item.get('url_name') == 'pagos_pendientes' for item in pantallas)
    ya_tiene_pagos_igss = any(item.get('url_name') == 'pagos_pendientes_igss' for item in pantallas)
    if usuario.puede_operar_caja:
        if not ya_tiene_caja:
            pantallas.append({'nombre': 'Caja - pagos de estudios', 'url_name': 'pagos_pendientes'})
        if not ya_tiene_pagos_igss:
            pantallas.append({'nombre': 'Pagos IGSS', 'url_name': 'pagos_pendientes_igss'})
    return pantallas


def buscar_pantalla(pantallas, clave):
    for pantalla in pantallas:
        if pantalla.get('clave') == clave:
            return pantalla
        for hija in pantalla.get('submenu', []):
            if hija.get('clave') == clave:
                return hija
    return None
