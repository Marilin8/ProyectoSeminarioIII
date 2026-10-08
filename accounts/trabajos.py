"""Un único trabajo largo a la vez (crear un respaldo o restaurar uno), con
progreso consultable desde la pantalla.

Waitress corre en un solo proceso con varios hilos, así que basta un estado en
memoria protegido con un candado. Si el servidor se reinicia a mitad de un
trabajo, el estado se pierde (el trabajo también). Con
RESPALDOS_EN_SEGUNDO_PLANO=False (pruebas) la tarea corre en el mismo hilo.
"""
import logging
import threading
import time

from django.conf import settings
from django.contrib import messages
from django.db import connections

logger = logging.getLogger(__name__)

_candado = threading.Lock()
_trabajo = None

NIVELES = {
    'success': messages.SUCCESS,
    'warning': messages.WARNING,
    'error': messages.ERROR,
}


def _en_segundo_plano():
    return getattr(settings, 'RESPALDOS_EN_SEGUNDO_PLANO', True)


def _ejecutar(trabajo, tarea, en_hilo):
    def progreso(porcentaje, etapa):
        trabajo['porcentaje'] = max(0, min(100, int(porcentaje)))
        trabajo['etapa'] = etapa

    try:
        trabajo['mensajes'] = tarea(progreso)
        trabajo['estado'] = 'ok'
    except Exception:
        logger.exception('Falló el trabajo de respaldo (%s)', trabajo['tipo'])
        trabajo['mensajes'] = [('error', 'Ocurrió un error inesperado (ver el registro del sistema).')]
        trabajo['estado'] = 'error'
    finally:
        trabajo['porcentaje'] = 100
        if en_hilo:
            connections.close_all()
        trabajo['terminado_en'] = time.time()


def iniciar(tipo, titulo, tarea):
    """Arranca `tarea(progreso)`, que debe devolver una lista de
    (nivel, texto). Devuelve False si ya hay otro trabajo en curso."""
    global _trabajo
    with _candado:
        if _trabajo is not None and _trabajo['estado'] == 'corriendo':
            return False
        trabajo = {
            'tipo': tipo, 'titulo': titulo, 'estado': 'corriendo', 'porcentaje': 0,
            'etapa': 'Iniciando…', 'mensajes': [], 'iniciado_en': time.time(),
        }
        _trabajo = trabajo
    if _en_segundo_plano():
        threading.Thread(target=_ejecutar, args=(trabajo, tarea, True), daemon=True).start()
    else:
        _ejecutar(trabajo, tarea, False)
    return True


def estado():
    """Copia del estado actual para mostrar en pantalla, o None."""
    trabajo = _trabajo
    if trabajo is None:
        return None
    return {
        'tipo': trabajo['tipo'],
        'titulo': trabajo['titulo'],
        'estado': trabajo['estado'],
        'porcentaje': trabajo['porcentaje'],
        'etapa': trabajo['etapa'],
        'segundos': int(time.time() - trabajo['iniciado_en']),
    }


def entregar_mensajes(request):
    """Si el último trabajo ya terminó, pasa su resultado a los mensajes de la
    página y lo da por entregado. Devuelve True si entregó algo."""
    global _trabajo
    with _candado:
        trabajo = _trabajo
        if trabajo is None or trabajo['estado'] == 'corriendo':
            return False
        _trabajo = None
    for nivel, texto in trabajo['mensajes']:
        messages.add_message(request, NIVELES.get(nivel, messages.INFO), texto)
    return True


def reiniciar():
    """Solo para pruebas: olvida cualquier trabajo."""
    global _trabajo
    with _candado:
        _trabajo = None
