import datetime

from django.utils import timezone

HORA_INICIO = 7
HORA_FIN = 17  # la última cita del día inicia poco antes de las 17:00
PASO_MINUTOS = 15  # granularidad de los horarios que se muestran en el calendario
LIMITE_DIAS_ADELANTE = 21  # no se puede agendar más de 3 semanas después de hoy

DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']


def horarios_disponibles():
    """Lista de datetime.time desde HORA_INICIO hasta HORA_FIN, cada PASO_MINUTOS."""
    momento = datetime.datetime.combine(datetime.date.today(), datetime.time(HORA_INICIO, 0))
    fin = datetime.datetime.combine(datetime.date.today(), datetime.time(HORA_FIN, 0))
    horarios = []
    while momento < fin:
        horarios.append(momento.time())
        momento += datetime.timedelta(minutes=PASO_MINUTOS)
    return horarios


def inicio_semana(fecha):
    return fecha - datetime.timedelta(days=fecha.weekday())


def en_el_pasado(fecha, hora):
    momento = timezone.make_aware(datetime.datetime.combine(fecha, hora))
    return momento < timezone.now()


def fuera_de_ventana(fecha):
    return fecha > datetime.date.today() + datetime.timedelta(days=LIMITE_DIAS_ADELANTE)


def rango_ocupado_por(fecha, hora, duracion_minutos):
    """(inicio, fin) que ocupa una cita de esa duración empezando en fecha/hora.
    Se usa para detectar si dos horarios se cruzan."""
    inicio = datetime.datetime.combine(fecha, hora)
    return inicio, inicio + datetime.timedelta(minutes=duracion_minutos)


def se_cruzan(rango_a, rango_b):
    return rango_a[0] < rango_b[1] and rango_a[1] > rango_b[0]
