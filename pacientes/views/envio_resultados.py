"""Envío de resultados al paciente y al médico tratante (correo + QR).

El envío se bloquea mientras el cobro de la cita no esté pagado, salvo COEX y
Emergencia IGSS, que no esperan el pago (ver ``_cobro_bloquea_envio``).
"""
import base64
import functools
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import sucursales
from accounts.models import Bitacora
from clinica.validators import avisar_si_correo_no_existe

from ..correos import (
    enviar_estudio_medico_tratante,
    enviar_resultados,
    link_visor_paciente,
    qr_data_uri,
    qr_png,
)
from ..forms import IngresarCorreoEnvioForm
from ..models import Cita, OrdenTrabajo
from .permisos import es_recepcionista


def _cobro_bloquea_envio(cita):
    """True si la cita tiene un cobro registrado que sigue pendiente: en ese
    caso no se permite enviar los resultados hasta que se marque como
    cobrado desde Caja. Si no hay cobro (todavía no se generó orden, o la
    orden es de antes de este permiso), no bloquea — el cobro no es
    obligatorio. Portado (2026-09-04) desde la rama visual-andres de
    TechBlood.

    Solo Privado: COEX y Emergencia IGSS no esperan el pago (ver
    Cita.cobro_bloquea_envio)."""
    return cita.cobro_bloquea_envio


def _enviar_estudio_y_registrar(request, cita, orden):
    """Envía el estudio (asume que el paciente ya tiene correo) y deja
    constancia: bitácora, marca de tiempo y mensaje de éxito. Si el envío
    falla, avisa con el motivo concreto (ver enviar_resultados) en vez de
    dejar la pantalla reventar, y NO marca el estudio como enviado — así el
    botón sigue disponible para reintentar. Si el estudio tiene un cobro
    pendiente, no se envía."""
    if _cobro_bloquea_envio(cita):
        messages.error(
            request,
            f'El estudio de {cita.paciente} tiene un cobro pendiente. '
            'Primero marcá el cobro como realizado desde Caja para poder enviar los resultados.',
        )
        return

    error = enviar_resultados(orden)
    if error:
        messages.error(
            request,
            f'No se pudo enviar el estudio a {cita.paciente}: {error}. '
            'El estudio sigue marcado como no enviado, podés reintentar.',
        )
        return

    orden.resultados_enviados_en = timezone.now()
    orden.save(update_fields=['resultados_enviados_en'])

    Bitacora.registrar(
        request=request,
        usuario=request.user,
        accion=Bitacora.ACCION_ENVIAR_ESTUDIO,
        descripcion=f'Envió el estudio de {cita.paciente} (cita #{cita.id}) por correo.',
    )
    messages.success(request, f'Estudio enviado a {cita.paciente} ({cita.paciente.correo}).')


def _intentar_envio_automatico(request, cita):
    """Envía el estudio sin que recepción tenga que apretar el botón,
    únicamente para convenio privado: cuando ya está pagado, tiene todas
    las imágenes y el informe completo (cita en ESTADO_PROCESADA), y el
    paciente ya tenía un correo registrado de antes (si no lo tiene, no se
    le pide acá -- sigue quedando para que recepción lo envíe a mano una
    vez lo complete). Se llama desde los tres lugares donde se puede
    cumplir la última condición pendiente: adjuntar_informe, marcar_cobrado
    y pagar_orden_pago. Reutiliza _enviar_estudio_y_registrar para que
    quede igual de registrado (bitácora, mensaje, marca de enviado) que un
    envío manual. Devuelve True si efectivamente se envió."""
    if cita.convenio != Cita.CONVENIO_PRIVADO or cita.estado != Cita.ESTADO_PROCESADA:
        return False
    if not cita.paciente.correo:
        return False
    orden = OrdenTrabajo.objects.filter(cita=cita).first()
    if not orden or orden.resultados_enviados_en or not orden.imagenes_completas:
        return False
    if _cobro_bloquea_envio(cita):
        return False
    _enviar_estudio_y_registrar(request, cita, orden)
    return True


def _intentar_envio_medico_tratante(request, cita, orden):
    """Si la cita tiene médico tratante y es privado o ambos (ver
    MedicoTratante.recibe_estudios_privados), le manda por correo el enlace
    del visor del estudio con su DPI como llave de acceso -- independiente
    del convenio de la cita y de si ya se le enviaron los resultados al
    paciente (ver enviado_medico_tratante_en en OrdenTrabajo). No bloquea
    nada si falla o si al médico le falta DPI/correo: solo deja un aviso,
    igual que el envío al paciente. Devuelve True si efectivamente se
    envió."""
    medico = cita.medico_tratante
    if not medico or not medico.recibe_estudios_privados or orden.enviado_medico_tratante_en:
        return False
    if not medico.correo or not medico.llave_de_acceso:
        messages.warning(
            request,
            f'El médico tratante {medico.nombre} es {medico.get_tipo_display()} pero le falta '
            'correo o llave de acceso (DPI, colegiado u OTP): no se le pudo enviar el estudio. Completá sus datos '
            'desde "Médicos tratantes".',
        )
        return False

    error = enviar_estudio_medico_tratante(orden)
    if error:
        messages.warning(
            request, f'No se pudo enviar el estudio al médico tratante {medico.nombre}: {error}.',
        )
        return False

    orden.enviado_medico_tratante_en = timezone.now()
    orden.save(update_fields=['enviado_medico_tratante_en'])
    messages.success(request, f'Estudio enviado también al médico tratante {medico.nombre} ({medico.correo}).')
    return True


@login_required
@user_passes_test(es_recepcionista)
@require_POST
def enviar_estudio(request, cita_id):
    """Envía los resultados del estudio al correo del paciente, a mano
    desde "Estudios realizados" (botón "Enviar estudio"/"Reenviar
    estudio"). Para convenio privado con correo ya registrado esto suele
    pasar solo (ver _intentar_envio_automatico); este botón sigue
    existiendo para los demás casos y para reenviar o completar el correo
    cuando falta. Si el paciente todavía no tiene correo registrado,
    primero la manda a completarlo."""
    cita = get_object_or_404(sucursales.permitidas(Cita.objects, request.user), id=cita_id, estado=Cita.ESTADO_PROCESADA)
    orden = OrdenTrabajo.objects.filter(cita=cita).first()
    if not orden:
        messages.error(
            request,
            'Este estudio no tiene una orden de trabajo. No se puede enviar hasta que '
            'Técnico y Radiología completen el flujo.',
        )
        return redirect('historial_paciente', paciente_id=cita.paciente_id)

    if not cita.paciente.correo:
        return redirect('ingresar_correo_envio', cita_id=cita.id)

    _enviar_estudio_y_registrar(request, cita, orden)
    return redirect('historial_paciente', paciente_id=cita.paciente_id)


@functools.lru_cache(maxsize=1)
def _logo_cime_data_uri():
    """Logo de CIME como data URI para la hoja del QR. Se incrusta en vez de usar
    {% static %} para que la hoja no dependa de haber corrido collectstatic.
    Devuelve '' si el archivo no está (la hoja entonces muestra solo el título)."""
    ruta = Path(settings.BASE_DIR) / 'static' / 'img' / 'logo_cime.png'
    try:
        return 'data:image/png;base64,' + base64.b64encode(ruta.read_bytes()).decode('ascii')
    except OSError:
        return ''


@login_required
@user_passes_test(es_recepcionista)
def qr_estudio(request, cita_id):
    """Código QR de los resultados del estudio, para entregarlo en persona
    (en pantalla o impreso) además del correo. Codifica el MISMO enlace que
    el correo: abre el visor, que sigue pidiendo el DPI. Misma regla que el
    envío por correo: no se entrega mientras el cobro siga pendiente.
    `?formato=png` descarga la imagen."""
    cita = get_object_or_404(
        sucursales.permitidas(Cita.objects.select_related('paciente', 'tipo_estudio'), request.user),
        id=cita_id, estado=Cita.ESTADO_PROCESADA,
    )
    orden = OrdenTrabajo.objects.filter(cita=cita).first()
    volver = redirect('historial_paciente', paciente_id=cita.paciente_id)
    if not orden:
        messages.error(request, 'Este estudio no tiene una orden de trabajo todavía.')
        return volver
    if _cobro_bloquea_envio(cita):
        messages.error(
            request,
            'No se puede entregar el QR: el estudio tiene un cobro pendiente. '
            'Primero registrá el pago en la pantalla de Caja.',
        )
        return volver

    enlace = link_visor_paciente(orden)
    if request.GET.get('formato') == 'png':
        respuesta = HttpResponse(qr_png(enlace), content_type='image/png')
        respuesta['Content-Disposition'] = f'attachment; filename="qr_resultados_{orden.id}.png"'
        return respuesta

    return render(request, 'pacientes/qr_estudio.html', {
        'cita': cita,
        'paciente': cita.paciente,
        'qr_data_uri': qr_data_uri(enlace),
        'logo_data_uri': _logo_cime_data_uri(),
        'volver_url': reverse('historial_paciente', args=[cita.paciente_id]),
    })


@login_required
@user_passes_test(es_recepcionista)
def ingresar_correo_envio(request, cita_id):
    """El paciente no tenía correo registrado al momento de enviar el
    estudio: pide el correo acá y, al guardarlo, envía el estudio de una
    vez (sin que la recepcionista tenga que volver a apretar "Enviar
    estudio")."""
    cita = get_object_or_404(sucursales.permitidas(Cita.objects, request.user), id=cita_id, estado=Cita.ESTADO_PROCESADA)
    orden = get_object_or_404(sucursales.permitidas(OrdenTrabajo.objects, request.user, 'cita__sucursal'), cita=cita)

    if cita.paciente.correo:
        # Ya se completó (ej. en otra pestaña); no hace falta este paso,
        # se envía directo.
        _enviar_estudio_y_registrar(request, cita, orden)
        return redirect('historial_paciente', paciente_id=cita.paciente_id)

    if request.method == 'POST':
        form = IngresarCorreoEnvioForm(request.POST)
        if form.is_valid():
            paciente = cita.paciente
            paciente.correo = form.cleaned_data['correo']
            paciente.save(update_fields=['correo'])
            _enviar_estudio_y_registrar(request, cita, orden)
            return redirect('historial_paciente', paciente_id=cita.paciente_id)
    else:
        form = IngresarCorreoEnvioForm()

    if request.method == 'POST':
        avisar_si_correo_no_existe(request, form)

    return render(request, 'pacientes/ingresar_correo_envio.html', {
        'form': form,
        'cita': cita,
    })
