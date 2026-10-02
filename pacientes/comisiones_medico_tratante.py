"""Cálculo de comisiones por referencia de médicos tratantes.

Solo cuentan las citas de convenio Privado ya procesadas (igual que
accounts.planilla usa Cita.ESTADO_PROCESADA para las comisiones de técnicos
y radiólogos): recién ahí el estudio tiene un precio final confirmado. No
hay un % de comisión guardado -- el administrador ve cuántas citas refirió
el médico y cuánto suman, y decide a mano cuánto pagarle según el contrato
que tenga (ver PagoComisionMedicoTratante)."""

from decimal import Decimal

from .models import Cita


def citas_referidas(medico, desde, hasta):
    """Citas Privado procesadas que refirió `medico` en [desde, hasta]
    (ambos incluidos), más antiguas primero."""
    return (
        Cita.objects.filter(
            medico_tratante=medico, convenio=Cita.CONVENIO_PRIVADO,
            estado=Cita.ESTADO_PROCESADA, fecha__gte=desde, fecha__lte=hasta,
        )
        .select_related('paciente', 'tipo_estudio')
        .order_by('fecha', 'hora')
    )


def citas_pendientes_de_pago(medico, desde, hasta):
    """Igual que citas_referidas, pero solo las que todavía no están
    cubiertas por ningún PagoComisionMedicoTratanteLinea."""
    return citas_referidas(medico, desde, hasta).filter(pago_comision_medico_tratante__isnull=True)


def primera_fecha_pendiente(medico):
    """Fecha de la cita procesada más antigua de `medico` que todavía no se
    pagó, sin límite de rango -- para que el reporte arranque ahí cuando no
    se elige un rango a mano (ver reporte_comision_medico_tratante)."""
    cita = (
        Cita.objects.filter(
            medico_tratante=medico, convenio=Cita.CONVENIO_PRIVADO,
            estado=Cita.ESTADO_PROCESADA, pago_comision_medico_tratante__isnull=True,
        )
        .order_by('fecha')
        .first()
    )
    return cita.fecha if cita else None


def resumen(citas):
    """Cantidad y total de una lista/queryset de citas (usa Cita.precio,
    que ya incluye los estudios extra marcados procesar_ahora)."""
    citas = list(citas)
    total = sum((c.precio for c in citas), Decimal('0.00'))
    return {'citas': citas, 'cantidad': len(citas), 'total': total}
