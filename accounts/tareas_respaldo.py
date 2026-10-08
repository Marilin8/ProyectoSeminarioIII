"""Tareas largas de respaldo (crear, subir a Drive, restaurar) pensadas para
correr con accounts.trabajos: cada una devuelve una función
`tarea(progreso) -> [(nivel, texto), ...]` que no depende de la petición web
(por eso reciben el usuario y la IP ya extraídos)."""
import logging
import shutil
from pathlib import Path

from . import nube as servicio_nube
from . import respaldos as servicio_respaldos
from .models import Bitacora, ConexionGoogleDrive, RespaldoEnNube, Usuario

logger = logging.getLogger(__name__)


def _bitacora(usuario_id, ip, accion, descripcion):
    # Tras una restauración el usuario puede ya no existir en la base restaurada.
    if usuario_id and not Usuario.objects.filter(pk=usuario_id).exists():
        usuario_id = None
    Bitacora.objects.create(usuario_id=usuario_id, accion=accion, descripcion=descripcion, ip=ip)


def subir_a_drive(nombre, usuario_id, ip):
    """Sube un respaldo a Google Drive. Devuelve (nivel, texto)."""
    conexion = ConexionGoogleDrive.objects.first()
    ruta = servicio_respaldos.ruta_respaldo(nombre)
    if conexion is None or not conexion.conectada or ruta is None:
        return 'warning', 'El respaldo quedó en el servidor, pero Google Drive no está conectado.'
    try:
        token = servicio_nube.token_de_acceso(
            conexion.client_id,
            servicio_nube.descifrar(conexion.client_secret_cifrado),
            servicio_nube.descifrar(conexion.refresh_token_cifrado),
        )
        file_id = servicio_nube.subir_archivo(token, ruta, conexion.carpeta_id)
    except servicio_nube.ErrorNube as error:
        return 'warning', f'El respaldo quedó en el servidor, pero no se subió a Google Drive: {error}'
    RespaldoEnNube.objects.update_or_create(nombre=nombre, defaults={'drive_file_id': file_id})
    _bitacora(
        usuario_id, ip, Bitacora.ACCION_SUBIR_RESPALDO,
        f'Subió el respaldo {nombre} a Google Drive ({conexion.correo_cuenta}).',
    )
    return 'success', f'Respaldo {nombre} subido a Google Drive ({conexion.correo_cuenta}).'


def crear(incluir_archivos, subir_drive, usuario_id, ip):
    def tarea(progreso):
        try:
            nombre = servicio_respaldos.crear_respaldo(incluir_archivos=incluir_archivos, progreso=progreso)
        except servicio_respaldos.ErrorRespaldo as error:
            return [('error', f'No se pudo crear el respaldo: {error}')]
        contenido = 'incluye archivos' if incluir_archivos else 'solo base de datos'
        _bitacora(usuario_id, ip, Bitacora.ACCION_CREAR_RESPALDO, f'Creó el respaldo {nombre} ({contenido}).')
        mensajes = [('success', f'Respaldo creado: {nombre}.')]
        if subir_drive:
            progreso(97, 'Subiendo a Google Drive…')
            mensajes.append(subir_a_drive(nombre, usuario_id, ip))
        return mensajes
    return tarea


def subir(nombre, usuario_id, ip):
    def tarea(progreso):
        progreso(10, 'Subiendo a Google Drive…')
        return [subir_a_drive(nombre, usuario_id, ip)]
    return tarea


def restaurar(ruta_subida, restaurar_archivos, usuario_id, ip, nombre_original):
    def tarea(progreso):
        try:
            seguridad, archivos = servicio_respaldos.restaurar(
                ruta_subida, restaurar_archivos=restaurar_archivos, progreso=progreso,
            )
        except servicio_respaldos.ErrorRespaldo as error:
            return [('error', f'No se restauró nada: {error}')]
        finally:
            shutil.rmtree(Path(ruta_subida).parent, ignore_errors=True)
        _bitacora(
            usuario_id, ip, Bitacora.ACCION_RESTAURAR_RESPALDO,
            f'Restauró el sistema desde {nombre_original}. Estado anterior guardado en {seguridad}.',
        )
        texto = (
            f'Restauración completa desde {nombre_original}. El estado anterior quedó guardado '
            f'en el respaldo {seguridad}.'
        )
        if archivos:
            texto += f' Se restauraron {archivos} imágenes e informes.'
        return [('success', texto)]
    return tarea
