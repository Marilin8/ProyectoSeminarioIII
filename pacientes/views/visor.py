"""Visor web de estudios para pacientes y médicos tratantes.

El paciente entra con el enlace/QR firmado; el médico tratante además confirma
un código OTP enviado por correo (con límite de intentos y de reenvíos).
"""
import base64
import binascii
import os
import secrets
import time
import zipfile
from io import BytesIO

from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.clickjacking import xframe_options_sameorigin

from accounts import limitador

from ..correos import enviar_codigo_otp_medico
from ..models import Cita, InformeEstudio, MedicoTratante, OrdenTrabajo


# ---------------------------------------------------------------------------
# Visor web público del estudio
#
# El correo de resultados manda un link estilo PACS:
#   /visor/?studyId=<id de la orden>&tab=images&ac=<token en base64>
#
#   - studyId: identifica el estudio (no es secreto)
#   - ac: token de acceso (UUID en base64; sin esto no abre)
#
# Para abrirlo el paciente ingresa además su DPI completo;
# tras eso queda autorizado en la sesión y puede ver las imágenes que la
# radióloga dejó seleccionadas y descargar el informe. No requiere login.
# ---------------------------------------------------------------------------

VISOR_MAX_INTENTOS = 5


def _ac_a_token(ac):
    """Decodifica el parámetro ac (base64 url-safe, sin padding) al token."""
    try:
        relleno = '=' * (-len(ac) % 4)
        return base64.urlsafe_b64decode(ac + relleno).decode('ascii')
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


def _visor_orden_desde_request(request):
    """Obtiene la orden a partir de ``studyId`` y ``ac`` (token público en
    base64) de la URL. 404 si no coinciden o si los resultados todavía no
    se enviaron a nadie."""
    study_id = request.GET.get('studyId')
    token = _ac_a_token(request.GET.get('ac') or '')
    if not (study_id or '').isdigit() or not token:
        raise Http404
    orden = get_object_or_404(
        OrdenTrabajo.objects.select_related(
            'cita__paciente', 'cita__tipo_estudio', 'cita__medico_tratante',
        ),
        id=study_id, token_publico=token,
    )
    # El mismo token sirve para el visor del paciente y el del médico
    # tratante (visor_estudio_medico_tratante): cada uno se marca por
    # separado (resultados_enviados_en / enviado_medico_tratante_en) y
    # pide el DPI de la persona correspondiente antes de mostrar nada.
    if not (orden.resultados_enviados_en or orden.enviado_medico_tratante_en):
        raise Http404
    return orden


def _historial_clinico(paciente, orden_actual):
    """Otros estudios ya procesados de este paciente (cualquier convenio,
    médico tratante o no), para el panel lateral del visor -- el historial
    clínico completo, no solo lo que el médico tratante actual refirió (ver
    visor_estudio_historial)."""
    return list(
        OrdenTrabajo.objects.filter(
            cita__paciente=paciente, cita__estado=Cita.ESTADO_PROCESADA,
        )
        .exclude(id=orden_actual.id)
        .select_related('cita__tipo_estudio')
        .order_by('-cita__fecha', '-cita__hora')
    )


def _render_visor_estudio(request, orden):
    """Renderiza el visor: imágenes seleccionadas por la radióloga, informes,
    sugerencias de estudio extra e historial clínico del paciente."""
    paciente = orden.cita.paciente
    imagenes = list(
        orden.imagenes.filter(seleccionada=True).exclude(archivo='').order_by('subida_en')
    )
    informes = list(orden.informes.select_related('tipo_estudio').all())
    return render(request, 'pacientes/visor_estudio.html', {
        'orden': orden,
        'cita': orden.cita,
        'paciente': paciente,
        'imagenes': imagenes,
        'tab': 'report' if request.GET.get('tab') == 'report' else 'images',
        'informes': informes,
        'tiene_pdf': any(i.archivo for i in informes),
        'tiene_dicom': any(img.archivo_original for img in imagenes),
        'edad': paciente.edad_en(orden.cita.fecha),
        # Estudios extra que la radióloga dejó solo como sugerencia (sin
        # "procesar ahora", ver EstudioExtra): ni el paciente ni el médico
        # tratante reciben un correo aparte por esto -- se enteran acá, al
        # entrar a ver sus resultados.
        'sugerencias_estudio_extra': list(
            orden.cita.estudios_extra.filter(procesar_ahora=False).select_related('tipo_estudio')
        ),
        'historial': _historial_clinico(paciente, orden),
    })


def visor_estudio(request):
    """Visor público del paciente (enlace/QR del correo). Antes de mostrar
    nada pide el DPI completo, con un máximo de ``VISOR_MAX_INTENTOS``
    intentos por sesión."""
    orden = _visor_orden_desde_request(request)
    _visor_otp_limpiar_si_vencio(request)
    paciente = orden.cita.paciente
    clave_ok = f'visor_ok_{orden.id}'
    clave_intentos = f'visor_intentos_{orden.id}'
    qs = request.META.get('QUERY_STRING', '')

    if request.session.get(clave_ok) is not True:
        intentos = request.session.get(clave_intentos, 0)
        contexto = {'paciente': paciente, 'query_string': qs}

        if request.method == 'POST':
            if intentos >= VISOR_MAX_INTENTOS:
                contexto['bloqueado'] = True
                return render(request, 'pacientes/visor_gate.html', contexto)
            dpi_ingresado = (request.POST.get('dpi_ultimos') or '').strip()
            if dpi_ingresado and dpi_ingresado == (paciente.dpi or ''):
                request.session[clave_ok] = True
                # El paciente queda autorizado a navegar TODO su historial
                # clínico desde acá (ver _historial_clinico/
                # visor_estudio_historial), no solo esta orden puntual.
                request.session[f'visor_paciente_ok_{paciente.id}'] = True
                request.session.pop(clave_intentos, None)
                return redirect(f'{reverse("visor_estudio")}?{qs}')
            request.session[clave_intentos] = intentos + 1
            contexto['error'] = 'El DPI no coincide con el registrado.'
            contexto['intentos_restantes'] = VISOR_MAX_INTENTOS - (intentos + 1)
            return render(request, 'pacientes/visor_gate.html', contexto)

        contexto['bloqueado'] = intentos >= VISOR_MAX_INTENTOS
        return render(request, 'pacientes/visor_gate.html', contexto)

    return _render_visor_estudio(request, orden)


VISOR_OTP_VALIDEZ_MINUTOS = 10
VISOR_OTP_ESPERA_REENVIO_SEGUNDOS = 60
VISOR_OTP_SESION_MINUTOS = 60


def _otp_hash(orden_id, codigo):
    """HMAC del código OTP: en la sesión nunca se guarda el código en claro."""
    return salted_hmac('visor_otp_medico', f'{orden_id}:{codigo}').hexdigest()


def _otp_enmascarar_correo(correo):
    """Oculta parte del correo para mostrarlo: "ju*****@dominio.com"."""
    usuario, _, dominio = correo.partition('@')
    return f'{usuario[:2]}{"*" * max(len(usuario) - 2, 1)}@{dominio}'


def _visor_otp_limpiar_si_vencio(request):
    """El acceso que se ganó con un código OTP dura VISOR_OTP_SESION_MINUTOS: pasado ese
    tiempo se vuelve a pedir un código nuevo (el DPI, en cambio, no vence en la sesión).
    Al vencer se borran las banderas de acceso de esta sesión."""
    hasta = request.session.get('visor_otp_hasta')
    if hasta is None or time.time() <= hasta:
        return
    for clave in list(request.session.keys()):
        if clave.startswith(('visor_ok_', 'visor_paciente_ok_', 'visor_otp_')):
            del request.session[clave]


def _visor_otp_enviar(request, orden, medico):
    """Genera un código de 6 dígitos, lo manda al correo del médico y lo deja
    pendiente en la sesión (solo su hash). Devuelve (enviado, mensaje_de_error)."""
    ahora = time.time()
    espera = limitador.OTP_ENVIOS_MEDICO.espera(orden.id)
    if espera:
        return False, (
            'Ya se enviaron demasiados códigos para este estudio. Intente de nuevo en '
            f'{limitador.minutos_de_espera(espera)} minuto(s).'
        )
    pendiente = request.session.get(f'visor_otp_pendiente_{orden.id}')
    if pendiente and ahora < pendiente['envio'] + VISOR_OTP_ESPERA_REENVIO_SEGUNDOS:
        faltan = int(pendiente['envio'] + VISOR_OTP_ESPERA_REENVIO_SEGUNDOS - ahora) + 1
        return False, f'Espere {faltan} segundo(s) antes de pedir otro código.'

    codigo = f'{secrets.randbelow(10 ** 6):06d}'
    limitador.OTP_ENVIOS_MEDICO.fallo(orden.id)
    error = enviar_codigo_otp_medico(medico, orden, codigo, VISOR_OTP_VALIDEZ_MINUTOS)
    if error:
        return False, f'No se pudo enviar el código: {error}.'
    request.session[f'visor_otp_pendiente_{orden.id}'] = {
        'h': _otp_hash(orden.id, codigo),
        'exp': ahora + VISOR_OTP_VALIDEZ_MINUTOS * 60,
        'n': 0,
        'envio': ahora,
    }
    return True, ''


def _visor_medico_con_otp(request, orden, medico, qs):
    """Pantalla de código OTP del médico tratante: valida el código enviado por
    correo (vence en ``VISOR_OTP_VALIDEZ_MINUTOS``, máximo de intentos) o lo
    reenvía respetando la espera entre envíos."""
    clave_pendiente = f'visor_otp_pendiente_{orden.id}'
    correo = _otp_enmascarar_correo(medico.correo)
    contexto = {'medico': medico, 'query_string': qs, 'modo_otp': True, 'correo_enmascarado': correo}

    if request.method == 'POST':
        if request.POST.get('accion') == 'reenviar':
            enviado, error = _visor_otp_enviar(request, orden, medico)
            if enviado:
                contexto['aviso'] = f'Le enviamos un código nuevo a {correo}.'
            else:
                contexto['error'] = error
            return render(request, 'pacientes/visor_gate.html', contexto)

        codigo = (request.POST.get('codigo') or '').strip()
        pendiente = request.session.get(clave_pendiente)
        if not pendiente or time.time() > pendiente['exp']:
            request.session.pop(clave_pendiente, None)
            contexto['error'] = 'El código venció o todavía no se envió. Pida uno nuevo.'
        elif constant_time_compare(pendiente['h'], _otp_hash(orden.id, codigo)):
            request.session.pop(clave_pendiente, None)
            request.session[f'visor_ok_{orden.id}'] = True
            request.session[f'visor_paciente_ok_{orden.cita.paciente_id}'] = True
            request.session['visor_otp_hasta'] = time.time() + VISOR_OTP_SESION_MINUTOS * 60
            return redirect(f'{reverse("visor_estudio")}?{qs}')
        else:
            pendiente['n'] += 1
            if pendiente['n'] >= VISOR_MAX_INTENTOS:
                request.session.pop(clave_pendiente, None)
                contexto['error'] = 'Demasiados intentos con este código. Pida uno nuevo.'
            else:
                request.session[clave_pendiente] = pendiente
                contexto['error'] = 'El código no es correcto.'
                contexto['intentos_restantes'] = VISOR_MAX_INTENTOS - pendiente['n']
        return render(request, 'pacientes/visor_gate.html', contexto)

    # Al abrir el enlace se manda el código solo, salvo que ya haya uno vigente.
    pendiente = request.session.get(clave_pendiente)
    if pendiente and time.time() <= pendiente['exp']:
        contexto['aviso'] = f'Ya le enviamos un código a {correo}. Revise su correo.'
    else:
        enviado, error = _visor_otp_enviar(request, orden, medico)
        if enviado:
            contexto['aviso'] = f'Le enviamos un código de 6 dígitos a {correo}.'
        else:
            contexto['error'] = error
    return render(request, 'pacientes/visor_gate.html', contexto)


def visor_estudio_medico_tratante(request):
    """Igual que visor_estudio pero para el médico tratante (correo
    enviado por enviar_estudio_medico_tratante). Se desbloquea con su llave de
    acceso (ver MedicoTratante.llave_de_acceso): un código de 6 dígitos que se le manda
    a su correo cada vez que abre el enlace (si tiene "acceso con código OTP"), su DPI o,
    si no tiene DPI, su número de colegiado. Una vez que entra, usa
    el mismo visor_estudio.html y las mismas descargas (visor_imagen/visor_jpg/
    visor_informe_pdf/visor_dicom): todas miran la misma bandera de sesión
    visor_ok_<orden>, sin importar quién la puso ahí."""
    orden = _visor_orden_desde_request(request)
    medico = orden.cita.medico_tratante
    if not medico or not medico.recibe_estudios_privados:
        raise Http404
    llave = medico.llave_de_acceso
    if llave is None:
        raise Http404
    _visor_otp_limpiar_si_vencio(request)
    clave_ok = f'visor_ok_{orden.id}'
    clave_intentos = f'visor_intentos_medico_{orden.id}'
    qs = request.META.get('QUERY_STRING', '')

    if request.session.get(clave_ok) is True:
        return redirect(f'{reverse("visor_estudio")}?{qs}')

    if llave == MedicoTratante.LLAVE_OTP:
        return _visor_medico_con_otp(request, orden, medico, qs)

    es_colegiado = llave == MedicoTratante.LLAVE_COLEGIADO
    esperado = (medico.numero_colegiado if es_colegiado else medico.dpi) or ''
    campo = 'colegiado' if es_colegiado else 'dpi_ultimos'
    nombre_llave = 'número de colegiado' if es_colegiado else 'DPI'
    intentos = request.session.get(clave_intentos, 0)
    contexto = {'medico': medico, 'query_string': qs, 'modo_colegiado': es_colegiado}
    bloqueado = intentos >= VISOR_MAX_INTENTOS or bool(limitador.LLAVE_MEDICO.espera(orden.id))

    if request.method == 'POST':
        if bloqueado:
            contexto['bloqueado'] = True
            return render(request, 'pacientes/visor_gate.html', contexto)
        ingresado = (request.POST.get(campo) or '').strip()
        if ingresado and constant_time_compare(ingresado, esperado):
            request.session[clave_ok] = True
            # El médico tratante también queda autorizado a navegar todo
            # el historial clínico de ESTE paciente desde acá, aunque no
            # haya sido él el médico tratante en esos otros estudios (ver
            # _historial_clinico/visor_estudio_historial).
            request.session[f'visor_paciente_ok_{orden.cita.paciente_id}'] = True
            request.session.pop(clave_intentos, None)
            return redirect(f'{reverse("visor_estudio")}?{qs}')
        request.session[clave_intentos] = intentos + 1
        limitador.LLAVE_MEDICO.fallo(orden.id)
        contexto['error'] = f'El {nombre_llave} no coincide con el registrado.'
        contexto['intentos_restantes'] = VISOR_MAX_INTENTOS - (intentos + 1)
        return render(request, 'pacientes/visor_gate.html', contexto)

    contexto['bloqueado'] = bloqueado
    return render(request, 'pacientes/visor_gate.html', contexto)


def visor_estudio_historial(request, orden_id):
    """Abre, desde el panel de historial clínico del visor, otro estudio ya
    procesado del MISMO paciente -- aunque nunca se haya enviado por correo
    ni este médico tratante haya participado en él (ver _historial_clinico).
    No es un link público: solo funciona dentro de una sesión ya autorizada
    para ese paciente (visor_paciente_ok_<paciente_id>, que ponen
    visor_estudio y visor_estudio_medico_tratante al validar el DPI)."""
    orden = get_object_or_404(
        OrdenTrabajo.objects.select_related('cita__paciente', 'cita__tipo_estudio'),
        id=orden_id, cita__estado=Cita.ESTADO_PROCESADA,
    )
    _visor_otp_limpiar_si_vencio(request)
    if request.session.get(f'visor_paciente_ok_{orden.cita.paciente_id}') is not True:
        raise Http404
    # Reusa las mismas descargas de imágenes/informe que el estudio de
    # entrada: _visor_orden_autorizada acepta esta misma bandera de sesión.
    request.session[f'visor_ok_{orden.id}'] = True
    return _render_visor_estudio(request, orden)


def _visor_orden_autorizada(request, orden_id):
    """Devuelve la orden si la sesión ya pasó el DPI/OTP para esa orden o para
    el paciente; si no, 404. Protege las descargas de imágenes y PDFs."""
    orden = get_object_or_404(OrdenTrabajo.objects.select_related('cita'), id=orden_id)
    _visor_otp_limpiar_si_vencio(request)
    if request.session.get(f'visor_paciente_ok_{orden.cita.paciente_id}') is True:
        return orden
    if request.session.get(f'visor_ok_{orden_id}') is True and (
        orden.resultados_enviados_en or orden.enviado_medico_tratante_en
    ):
        return orden
    raise Http404


def visor_imagen(request, orden_id, imagen_id):
    """Sirve una imagen JPG seleccionada de la orden (``?descargar=1`` la baja como archivo)."""
    orden = _visor_orden_autorizada(request, orden_id)
    imagen = get_object_or_404(
        orden.imagenes.filter(seleccionada=True).exclude(archivo=''), id=imagen_id,
    )
    descargar = request.GET.get('descargar') == '1'
    return FileResponse(
        imagen.archivo.open('rb'),
        as_attachment=descargar,
        filename=(
            f'{orden.cita.paciente.apellido}_{orden.cita.fecha}_{imagen_id}.jpg'
            if descargar else None
        ),
    )


def visor_jpg(request, orden_id):
    """Zip con las imágenes JPG seleccionadas, para descargar desde el visor
    (botón "Descargar JPG")."""
    orden = _visor_orden_autorizada(request, orden_id)
    imagenes = list(orden.imagenes.filter(seleccionada=True).exclude(archivo=''))
    if not imagenes:
        raise Http404

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for n, imagen in enumerate(imagenes, start=1):
            with imagen.archivo.open('rb') as fh:
                zf.writestr(f'imagen_{n:02d}.jpg', fh.read())
    buffer.seek(0)
    respuesta = HttpResponse(buffer.getvalue(), content_type='application/zip')
    respuesta['Content-Disposition'] = (
        f'attachment; filename="imagenes_{orden.cita.paciente.dpi}.zip"'
    )
    return respuesta


@xframe_options_sameorigin
def visor_informe_pdf(request, orden_id, informe_id):
    """Sirve el PDF del informe (se puede incrustar en el visor por el mismo origen)."""
    orden = _visor_orden_autorizada(request, orden_id)
    informe = get_object_or_404(InformeEstudio, id=informe_id, orden=orden)
    if not informe.archivo:
        raise Http404
    descargar = request.GET.get('descargar') == '1'
    return FileResponse(
        informe.archivo.open('rb'),
        as_attachment=descargar,
        content_type='application/pdf',
        filename=f'informe_{informe.tipo_estudio.nombre}_{orden.cita.paciente.apellido}_{orden.cita.fecha}.pdf',
    )


def visor_dicom(request, orden_id):
    """Zip con los DICOM originales de las imágenes seleccionadas, para que
    el paciente los baje desde el visor (botón "Descargar DICOM")."""
    orden = _visor_orden_autorizada(request, orden_id)
    imagenes = [
        img for img in orden.imagenes.filter(seleccionada=True) if img.archivo_original
    ]
    if not imagenes:
        raise Http404

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        usados = set()
        for imagen in imagenes:
            nombre = os.path.basename(imagen.archivo_original.name)
            base, ext = os.path.splitext(nombre)
            candidato, i = nombre, 1
            while candidato in usados:
                candidato, i = f'{base}_{i}{ext}', i + 1
            usados.add(candidato)
            with imagen.archivo_original.open('rb') as fh:
                zf.writestr(candidato, fh.read())
    buffer.seek(0)
    respuesta = HttpResponse(buffer.getvalue(), content_type='application/zip')
    respuesta['Content-Disposition'] = (
        f'attachment; filename="estudio_{orden.cita.paciente.dpi}.zip"'
    )
    return respuesta
