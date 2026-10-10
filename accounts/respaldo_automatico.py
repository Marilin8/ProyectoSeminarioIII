"""Copia de seguridad automática diaria: base de datos + imágenes/informes, subida a
Google Drive, conservando solo las últimas N (6 por defecto). Las copias que crea el
administrador a mano (prefijo `respaldo_`) nunca entran en esta rotación: solo se tocan
los archivos con prefijo `auto_`, tanto en el servidor como en Drive."""
import datetime
import logging

from django.conf import settings
from django.utils import timezone

from . import nube as servicio_nube
from . import respaldos as servicio_respaldos
from .models import Bitacora, ConexionGoogleDrive, EjecucionRespaldoAutomatico, RespaldoEnNube
from .tareas_respaldo import subir_a_drive

logger = logging.getLogger(__name__)

PREFIJO = servicio_respaldos.PREFIJO_AUTOMATICO


def _marca(nombre):
    """AAAAMMDD_HHMMSS del nombre: sirve para ordenar de la más antigua a la más nueva."""
    return nombre[len(PREFIJO):len(PREFIJO) + 15]


def nombres_automaticos():
    """Copias automáticas conocidas, en el servidor o en Drive, de la más antigua a la más
    nueva. Se cuentan las dos fuentes: si alguien borró el archivo local pero sigue en
    Drive (o al revés), igual cuenta hasta que desaparezca de los dos lados."""
    locales = {r['nombre'] for r in servicio_respaldos.listar_respaldos() if r['automatico']}
    en_drive = set(RespaldoEnNube.objects.filter(nombre__startswith=PREFIJO).values_list('nombre', flat=True))
    return sorted(locales | en_drive, key=_marca)


def _token_drive():
    conexion = ConexionGoogleDrive.objects.first()
    if conexion is None or not conexion.conectada:
        return None
    return servicio_nube.token_de_acceso(
        conexion.client_id,
        servicio_nube.descifrar(conexion.client_secret_cifrado),
        servicio_nube.descifrar(conexion.refresh_token_cifrado),
    )


def aplicar_retencion(conservar=None):
    """Deja solo las `conservar` copias automáticas más nuevas: borra el resto del servidor
    y de Drive. Lo que no se pueda borrar (Drive sin conexión, archivo en uso) se reintenta
    en la próxima corrida. Devuelve {'eliminados': [...], 'fallos': [...]}."""
    conservar = conservar or settings.RESPALDOS_AUTOMATICOS_CONSERVAR
    nombres = nombres_automaticos()
    sobrantes = nombres[:-conservar] if len(nombres) > conservar else []
    resultado = {'eliminados': [], 'fallos': []}
    token = None
    token_obtenido = False

    for nombre in sobrantes:
        drive_ok = True
        fila = RespaldoEnNube.objects.filter(nombre=nombre).first()
        if fila is not None:
            try:
                if not token_obtenido:
                    token, token_obtenido = _token_drive(), True
                if token is None:
                    raise servicio_nube.ErrorNube('Google Drive no está conectado')
                servicio_nube.borrar_archivo(token, fila.drive_file_id)
                fila.delete()
            except servicio_nube.ErrorNube as error:
                drive_ok = False
                resultado['fallos'].append(f'{nombre} en Google Drive: {error}')

        local_ok = True
        ruta = servicio_respaldos.ruta_respaldo(nombre)
        if ruta is not None:
            try:
                ruta.unlink()
            except OSError as error:
                local_ok = False
                resultado['fallos'].append(f'{nombre} en el servidor: {error.strerror or error}')

        if drive_ok and local_ok:
            resultado['eliminados'].append(nombre)
    return resultado


def _subir_pendientes(excluir):
    """Copias automáticas que quedaron solo en el servidor (una subida anterior falló) y que
    todavía se conservan: se vuelven a intentar subir."""
    subidas = []
    en_drive = set(RespaldoEnNube.objects.filter(nombre__startswith=PREFIJO).values_list('nombre', flat=True))
    for nombre in nombres_automaticos():
        if nombre == excluir or nombre in en_drive or servicio_respaldos.ruta_respaldo(nombre) is None:
            continue
        nivel, _texto = subir_a_drive(nombre, None, None)
        if nivel == 'success':
            subidas.append(nombre)
    return subidas


def ejecutar(progreso=None, incluir_archivos=None):
    """Crea la copia automática de ahora, la sube a Drive y rota las antiguas. Lanza
    ErrorRespaldo si no se pudo ni crear la copia (en ese caso no se borra nada)."""
    def avisar(porcentaje, etapa):
        if progreso:
            progreso(porcentaje, etapa)

    if incluir_archivos is None:
        incluir_archivos = settings.RESPALDOS_AUTOMATICOS_INCLUYEN_ARCHIVOS

    nombre = servicio_respaldos.crear_respaldo(
        incluir_archivos=incluir_archivos, prefijo=PREFIJO,
        progreso=lambda porcentaje, etapa: avisar(porcentaje * 0.88, etapa),
    )

    avisar(90, 'Subiendo la copia a Google Drive…')
    nivel, texto_drive = subir_a_drive(nombre, None, None)
    subida_ok = nivel == 'success'

    avisar(96, 'Borrando las copias automáticas más antiguas…')
    retencion = aplicar_retencion()
    reintentadas = _subir_pendientes(excluir=nombre) if subida_ok else []

    partes = [f'Copia automática creada: {nombre}.']
    if subida_ok:
        partes.append('Subida a Google Drive.')
    else:
        partes.append(f'No se pudo subir a Google Drive ({texto_drive}).')
    if reintentadas:
        partes.append(f'Se subieron {len(reintentadas)} copia(s) que habían quedado pendientes.')
    if retencion['eliminados']:
        partes.append('Se borró la más antigua: ' + ', '.join(retencion['eliminados']) + '.')
    if retencion['fallos']:
        partes.append('No se pudo borrar: ' + '; '.join(retencion['fallos']) + ' (se reintenta mañana).')
    texto = ' '.join(partes)

    Bitacora.objects.create(accion=Bitacora.ACCION_CREAR_RESPALDO, descripcion=texto[:2000])
    avisar(100, 'Listo')
    return {
        'nombre': nombre, 'subida_ok': subida_ok, 'texto': texto,
        'eliminados': retencion['eliminados'], 'fallos': retencion['fallos'],
    }


def estado_para_pantalla(ahora=None):
    """Datos de la tarjeta "Copias automáticas" de la pantalla de Respaldos."""
    ahora = timezone.localtime(ahora or timezone.now())
    ultima = EjecucionRespaldoAutomatico.objects.exclude(
        estado=EjecucionRespaldoAutomatico.ESTADO_OMITIDO,
    ).first()
    hay_hoy = EjecucionRespaldoAutomatico.objects.filter(fecha=ahora.date()).exists()
    proxima_fecha = ahora.date() + datetime.timedelta(days=1 if hay_hoy else 0)
    conexion = ConexionGoogleDrive.objects.first()
    return {
        'activo': bool(getattr(settings, 'RESPALDOS_AUTOMATICOS', False)),
        'conservar': settings.RESPALDOS_AUTOMATICOS_CONSERVAR,
        'incluye_archivos': settings.RESPALDOS_AUTOMATICOS_INCLUYEN_ARCHIVOS,
        'ultima': ultima,
        'proxima': datetime.datetime.combine(proxima_fecha, datetime.time.min),
        'drive_conectado': bool(conexion and conexion.conectada),
        'cantidad': len(nombres_automaticos()),
    }
