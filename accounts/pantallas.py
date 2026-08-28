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
                {'nombre': 'Pantalla de turnos', 'url_name': 'pantalla_turnos_emergencia'},
            ],
        },
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
    ],
}


def pantallas_de(usuario):
    if usuario.is_superuser and usuario.rol != Usuario.ROL_ADMINISTRADOR:
        return PANTALLAS_POR_ROL[Usuario.ROL_ADMINISTRADOR]
    return PANTALLAS_POR_ROL.get(usuario.rol, [])


def buscar_pantalla(pantallas, clave):
    for pantalla in pantallas:
        if pantalla.get('clave') == clave:
            return pantalla
        for hija in pantalla.get('submenu', []):
            if hija.get('clave') == clave:
                return hija
    return None
