"""Programador de la copia de seguridad automática: un hilo dentro del servidor (arrancado
desde clinica/wsgi.py) que cada minuto mira si ya toca la copia del día. Una copia por
fecha (a partir de las 00:00, hora de Guatemala); si el servidor estaba apagado a esa hora,
la hace apenas vuelva a estar encendido. Si falla, reintenta (máximo 3 veces por día, con 30
minutos entre intentos)."""
import datetime
import logging
import threading

from django.conf import settings
from django.db import connections
from django.db.models import F
from django.utils import timezone

from . import respaldo_automatico, trabajos
from .models import EjecucionRespaldoAutomatico as Ejecucion

logger = logging.getLogger(__name__)

MAX_INTENTOS_POR_DIA = 3
ESPERA_ENTRE_INTENTOS = datetime.timedelta(minutes=30)
EN_CURSO_SE_DA_POR_PERDIDO = datetime.timedelta(hours=3)
SEGUNDOS_ENTRE_REVISIONES = 60
SEGUNDOS_DE_GRACIA_AL_ARRANCAR = 60

_parada = threading.Event()
_candado = threading.Lock()
_hilo = None


def iniciar():
    """Arranca el hilo (una sola vez por proceso). No hace nada si las copias automáticas
    están apagadas (RESPALDOS_AUTOMATICOS=False, como en las pruebas)."""
    global _hilo
    if not getattr(settings, 'RESPALDOS_AUTOMATICOS', False):
        return False
    with _candado:
        if _hilo is not None and _hilo.is_alive():
            return False
        _parada.clear()
        _hilo = threading.Thread(target=_bucle, name='respaldo-automatico', daemon=True)
        _hilo.start()
    return True


def detener():
    _parada.set()


def _bucle():
    if _parada.wait(SEGUNDOS_DE_GRACIA_AL_ARRANCAR):  # deja que el servidor termine de arrancar
        return
    while not _parada.is_set():
        try:
            revisar()
        except Exception:
            logger.exception('Falló la revisión de la copia de seguridad automática')
        try:
            # De paso, que el reporte diario de cada convenio exista desde las 00:00.
            from pacientes.models import ReporteDiario
            ReporteDiario.asegurar_del_dia()
        except Exception:
            logger.exception('No se pudieron crear los reportes diarios de hoy')
        finally:
            connections.close_all()
        if _parada.wait(SEGUNDOS_ENTRE_REVISIONES):
            break


def _reintentable(ejecucion, ahora):
    if ejecucion.intentos >= MAX_INTENTOS_POR_DIA:
        return False
    if ejecucion.estado == Ejecucion.ESTADO_ERROR:
        return ahora - (ejecucion.terminado_en or ejecucion.iniciado_en) >= ESPERA_ENTRE_INTENTOS
    if ejecucion.estado == Ejecucion.ESTADO_EN_CURSO:
        # El servidor se reinició a mitad de la copia: quedó "en curso" para siempre.
        return ahora - ejecucion.iniciado_en > EN_CURSO_SE_DA_POR_PERDIDO
    return False  # ok / omitido: la copia de hoy ya está resuelta


def _tarea(ejecucion_id):
    def tarea(progreso):
        ejecucion = Ejecucion.objects.get(pk=ejecucion_id)
        try:
            resumen = respaldo_automatico.ejecutar(progreso)
        except Exception as error:
            logger.exception('Falló la copia de seguridad automática')
            ejecucion.estado = Ejecucion.ESTADO_ERROR
            ejecucion.detalle = f'{error}'[:2000]
            ejecucion.terminado_en = timezone.now()
            ejecucion.save(update_fields=['estado', 'detalle', 'terminado_en'])
            return [('error', f'Falló la copia de seguridad automática: {error}')]
        ejecucion.estado = Ejecucion.ESTADO_OK
        ejecucion.nombre = resumen['nombre']
        ejecucion.detalle = resumen['texto'][:2000]
        ejecucion.terminado_en = timezone.now()
        ejecucion.save(update_fields=['estado', 'nombre', 'detalle', 'terminado_en'])
        todo_bien = resumen['subida_ok'] and not resumen['fallos']
        return [('success' if todo_bien else 'warning', resumen['texto'])]
    return tarea


def revisar(ahora=None):
    """Una vuelta del programador. Devuelve el id de la ejecución que arrancó, o None."""
    ahora = ahora or timezone.now()
    hoy = timezone.localtime(ahora).date()

    if not Ejecucion.objects.exists():
        # Primera vez que se activa: no se hace una copia pesada en pleno día; la primera
        # copia automática es esta noche a las 00:00.
        Ejecucion.objects.get_or_create(fecha=hoy, defaults={
            'estado': Ejecucion.ESTADO_OMITIDO, 'intentos': 0, 'terminado_en': ahora,
            'detalle': 'Las copias automáticas se activaron hoy; la primera es a las 00:00.',
        })
        return None

    ejecucion = Ejecucion.objects.filter(fecha=hoy).first()
    estado_previo = None
    if ejecucion is None:
        ejecucion, creada = Ejecucion.objects.get_or_create(
            fecha=hoy, defaults={'estado': Ejecucion.ESTADO_EN_CURSO},
        )
        if not creada:
            return None  # otro proceso la reclamó primero
    else:
        if not _reintentable(ejecucion, ahora):
            return None
        estado_previo = ejecucion.estado
        reclamada = Ejecucion.objects.filter(pk=ejecucion.pk, estado=estado_previo).update(
            estado=Ejecucion.ESTADO_EN_CURSO, intentos=F('intentos') + 1,
            iniciado_en=ahora, terminado_en=None,
        )
        if not reclamada:
            return None

    if not trabajos.iniciar('respaldo', 'Copia de seguridad automática', _tarea(ejecucion.pk)):
        # Hay otro trabajo largo en curso (una copia o restauración manual): se devuelve el
        # reclamo sin gastar un intento y se prueba de nuevo en la próxima vuelta.
        if estado_previo is None:
            ejecucion.delete()
        else:
            Ejecucion.objects.filter(pk=ejecucion.pk).update(
                estado=estado_previo, intentos=F('intentos') - 1,
            )
        return None
    return ejecucion.pk
