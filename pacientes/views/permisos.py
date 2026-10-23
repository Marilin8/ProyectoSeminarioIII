"""Funciones de permiso por rol, usadas con ``@user_passes_test``.

Cada una recibe el usuario y devuelve True si puede entrar a la vista. Usan
``Usuario.tiene_rol``, que también cuenta los roles adicionales (un técnico que
además tiene habilitado el rol de radiólogo pasa ``es_radiologo``).

Ojo: ``es_tecnico``/``es_radiologo``/``es_recepcionista`` NO dejan pasar al
administrador; las vistas que también debe ver el admin combinan la función
con ``accounts.views.es_administrador``.
"""
from accounts.models import Usuario
from accounts.views import es_administrador


def es_recepcionista(user):
    """Rol de recepción (agenda, llegada de pacientes, turnos)."""
    return user.is_authenticated and user.tiene_rol(Usuario.ROL_RECEPCIONISTA)


def es_caja(user):
    """Puede operar la pantalla de Caja: por el permiso puede_operar_caja
    (independiente del rol) o por ser administrador. Portado (2026-09-04)
    desde la rama visual-andres de TechBlood."""
    return user.is_authenticated and (user.puede_operar_caja or es_administrador(user))


def puede_ver_comprobante_pago(user):
    """Personal autorizado a consultar el comprobante de un estudio pagado.
    HU-50/HU-52 (portado 2026-09-12 desde la rama visual-andres de
    TechBlood): además de Caja/administración, recepción, técnicos y
    radiólogos necesitan poder revisar la boleta/constancia mientras
    trabajan la orden."""
    return user.is_authenticated and (
        es_administrador(user)
        or es_administrador_financiero(user)
        or es_caja(user)
        or any(
            user.tiene_rol(rol) for rol in (
                Usuario.ROL_RECEPCIONISTA,
                Usuario.ROL_TECNICO_IMAGENES,
                Usuario.ROL_MEDICO_RADIOLOGO,
            )
        )
    )


def es_tecnico(user):
    """Técnico de imágenes (verifica el estudio y sube las imágenes)."""
    return user.is_authenticated and user.tiene_rol(Usuario.ROL_TECNICO_IMAGENES)


def es_radiologo(user):
    """Médico radiólogo (redacta y adjunta el informe)."""
    return user.is_authenticated and user.tiene_rol(Usuario.ROL_MEDICO_RADIOLOGO)


def es_administrador_financiero(user):
    """Administrador financiero o superusuario (reportes, planilla, finanzas)."""
    return user.is_authenticated and (
        user.is_superuser or user.tiene_rol(Usuario.ROL_ADMINISTRADOR_FINANCIERO)
    )


def puede_ver_reportes_diarios(user):
    """Recepción arma/consulta el reporte del día; finanzas y admin lo revisan."""
    return es_recepcionista(user) or es_administrador_financiero(user) or es_administrador(user)


def puede_descargar_reportes_diarios(user):
    """Solo finanzas y administración descargan el PDF/Excel del reporte."""
    return es_administrador_financiero(user) or es_administrador(user)
