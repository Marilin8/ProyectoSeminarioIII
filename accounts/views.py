import base64
import datetime
import io
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import urlencode
from django.views.decorators.http import require_POST
from django_otp.plugins.otp_totp.models import TOTPDevice

import qrcode

from .forms import (
    CambiarContrasenaForm,
    CrearUsuarioForm,
    EditarUsuarioForm,
    LoginForm,
    PerfilForm,
    RegistrarPagoPlanillaForm,
)
from .models import Bitacora, HistorialComision, LineaComisionLiquidada, PagoPlanilla, Usuario
from .pantallas import buscar_pantalla, pantallas_de


def es_administrador(user):
    return user.is_authenticated and (user.is_superuser or user.rol == Usuario.ROL_ADMINISTRADOR)


# Roles que se administran desde la pantalla "Usuarios activos". El nombre es
# el texto del botón/listado; el orden define el orden de los botones.
ROLES_GESTIONABLES = {
    Usuario.ROL_MEDICO_RADIOLOGO: 'Radiólogos',
    Usuario.ROL_TECNICO_IMAGENES: 'Técnicos',
    Usuario.ROL_RECEPCIONISTA: 'Secretarías',
}

_URL_LISTA_POR_ROL = {
    Usuario.ROL_MEDICO_RADIOLOGO: 'lista_usuarios_radiologos',
    Usuario.ROL_TECNICO_IMAGENES: 'lista_usuarios_tecnicos',
    Usuario.ROL_RECEPCIONISTA: 'lista_usuarios_secretarias',
}


def _url_lista_para(usuario):
    return _URL_LISTA_POR_ROL.get(usuario.rol, 'dashboard')


_DIAS_LARGOS_ES = [
    'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo',
]
_MESES_LARGOS_ES = [
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
    'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]


def _fecha_larga_es(fecha):
    """'lunes 1 de enero de 2026' en español."""
    dia_semana = _DIAS_LARGOS_ES[fecha.weekday()]
    mes = _MESES_LARGOS_ES[fecha.month - 1]
    return f'{dia_semana} {fecha.day} de {mes} de {fecha.year}'


# ---------------------------------------------------------------------------
# Inicio de sesión con verificación en dos pasos (MFA / TOTP)
# ---------------------------------------------------------------------------

def _dispositivo_totp(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).first()


def login(request):
    """Primer paso: usuario y contraseña. Si el usuario tiene MFA activado,
    manda al segundo paso; si no, entra directo."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    form = LoginForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        if _dispositivo_totp(user):
            request.session['mfa_user_id'] = user.pk
            return redirect('login_otp')
        auth_login(request, user)
        return redirect(request.GET.get('next') or 'dashboard')

    return render(request, 'registration/login.html', {'form': form})


def login_otp(request):
    """Segundo paso: código de 6 dígitos de la app de autenticación. Solo
    llega acá quien ya pasó usuario+contraseña en `login`."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    user_id = request.session.get('mfa_user_id')
    if not user_id:
        messages.error(request, 'Primero ingresá tu usuario y contraseña.')
        return redirect('login')

    user = get_object_or_404(Usuario, pk=user_id)
    if request.method == 'POST':
        codigo = (request.POST.get('codigo') or '').strip()
        device = _dispositivo_totp(user)
        if device is not None and device.verify_token(codigo):
            request.session.pop('mfa_user_id', None)
            auth_login(request, user)
            return redirect('dashboard')
        messages.error(request, 'El código no es válido o ya expiró.')

    return render(request, 'accounts/login_otp.html', {'usuario_login': user})


@login_required
def configurar_mfa(request):
    """El usuario activa o desactiva la verificación en dos pasos. Muestra el
    QR para vincular la app y pide un primer código para confirmar."""
    device = TOTPDevice.objects.filter(user=request.user).first()

    if request.method == 'POST':
        accion = request.POST.get('accion')

        if accion == 'desactivar' and device is not None:
            device.delete()
            messages.success(request, 'Verificación en dos pasos desactivada.')
            return redirect('configurar_mfa')

        if accion == 'regenerar' and device is not None:
            device.delete()
            device = None

        if accion == 'verificar':
            codigo = (request.POST.get('codigo') or '').strip()
            if device is not None and device.verify_token(codigo):
                if not device.confirmed:
                    device.confirmed = True
                    device.save(update_fields=['confirmed'])
                Bitacora.registrar(
                    request=request, usuario=request.user,
                    accion=Bitacora.ACCION_EDITAR_USUARIO,
                    descripcion=f'"{request.user.username}" activó la verificación en dos pasos.',
                )
                messages.success(
                    request,
                    'Verificación en dos pasos activada. Desde ahora, cada inicio de '
                    'sesión va a pedir un código de la app.',
                )
                return redirect('configurar_mfa')
            messages.error(
                request,
                'El código no coincide. Revisá la hora de tu teléfono e intentá de nuevo.',
            )
            return redirect('configurar_mfa')

    if device is None:
        device = TOTPDevice.objects.create(user=request.user, confirmed=False)

    return render(request, 'accounts/configurar_mfa.html', {
        'confirmado': device.confirmed,
        'qr_data_uri': None if device.confirmed else _qr_data_uri(device),
        'clave_manual': None if device.confirmed else _clave_manual(device),
    })


def _qr_data_uri(device):
    """Imagen QR (data URI PNG) con el enlace otpauth:// del dispositivo."""
    try:
        buffer = io.BytesIO()
        qrcode.make(device.config_url).save(buffer, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')
    except Exception:
        return None


def _clave_manual(device):
    """La clave base32 en grupos de 4, para escribirla a mano si no se puede
    escanear el QR."""
    try:
        import re
        clave = re.search(r'secret=([A-Z2-7]+)', device.config_url).group(1)
        return ' '.join(clave[i:i + 4] for i in range(0, len(clave), 4))
    except Exception:
        return None


@login_required
def dashboard(request):
    return render(request, 'accounts/dashboard.html', {'pantallas': pantallas_de(request.user)})


@login_required
def mi_perfil(request):
    """Cada usuario ve y edita sus propios datos (nombres, apellidos, correo)
    y puede cambiar su contraseña. No puede tocar su rol, comisiones ni
    estado: eso solo lo hace un administrador desde 'Usuarios activos'."""
    perfil_form = PerfilForm(instance=request.user)
    password_form = CambiarContrasenaForm(user=request.user)

    if request.method == 'POST' and 'guardar_perfil' in request.POST:
        perfil_form = PerfilForm(request.POST, instance=request.user)
        if perfil_form.is_valid():
            perfil_form.save()
            Bitacora.registrar(
                request=request, usuario=request.user,
                accion=Bitacora.ACCION_EDITAR_USUARIO,
                descripcion=f'"{request.user.username}" editó los datos de su propio perfil.',
            )
            messages.success(request, 'Perfil actualizado correctamente.')
            return redirect('mi_perfil')

    elif request.method == 'POST' and 'cambiar_contrasena' in request.POST:
        password_form = CambiarContrasenaForm(user=request.user, data=request.POST)
        if password_form.is_valid():
            password_form.save()
            update_session_auth_hash(request, password_form.user)
            Bitacora.registrar(
                request=request, usuario=request.user,
                accion=Bitacora.ACCION_EDITAR_USUARIO,
                descripcion=f'"{request.user.username}" cambió su contraseña.',
            )
            messages.success(request, 'Contraseña actualizada correctamente.')
            return redirect('mi_perfil')

    return render(request, 'accounts/mi_perfil.html', {
        'perfil_form': perfil_form,
        'password_form': password_form,
        'mfa_activo': _dispositivo_totp(request.user) is not None,
    })


@login_required
def pantalla_placeholder(request, clave):
    pantalla = buscar_pantalla(pantallas_de(request.user), clave)
    if pantalla is None:
        raise Http404
    if pantalla.get('submenu'):
        return render(request, 'accounts/submenu.html', {'pantalla': pantalla})
    return render(request, 'accounts/en_construccion.html', {'pantalla': pantalla})


@login_required
@user_passes_test(es_administrador)
def crear_usuario(request):
    if request.method == 'POST':
        form = CrearUsuarioForm(request.POST)
        if form.is_valid():
            nuevo_usuario = form.save()
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_CREAR_USUARIO,
                descripcion=(
                    f'Creó el usuario "{nuevo_usuario.username}" con rol '
                    f'{nuevo_usuario.get_rol_display()}.'
                ),
            )
            messages.success(request, f'Usuario "{nuevo_usuario.username}" creado correctamente.')
            return redirect('dashboard')
    else:
        form = CrearUsuarioForm()
    return render(request, 'accounts/crear_usuario.html', {'form': form})


@login_required
@user_passes_test(es_administrador)
def lista_usuarios(request, rol):
    if rol not in ROLES_GESTIONABLES:
        raise Http404
    usuarios = Usuario.objects.filter(rol=rol).order_by('-is_active', 'first_name', 'last_name', 'username')
    if rol == Usuario.ROL_MEDICO_RADIOLOGO:
        from pacientes.models import TipoEstudio

        total_estudios = TipoEstudio.objects.filter(activo=True).count()
        usuarios = usuarios.annotate(n_estudios=Count('tipos_estudio_asignados')).prefetch_related(
            Prefetch(
                'tipos_estudio_asignados',
                queryset=TipoEstudio.objects.order_by('modalidad', 'nombre'),
            )
        )
    else:
        total_estudios = 0
    return render(request, 'accounts/lista_usuarios.html', {
        'usuarios': usuarios,
        'rol': rol,
        'rol_label': ROLES_GESTIONABLES[rol],
        'es_radiologo': rol == Usuario.ROL_MEDICO_RADIOLOGO,
        'total_estudios': total_estudios,
        'roles_gestionables': ROLES_GESTIONABLES,
    })


def _periodo_planilla(request):
    """Resuelve el período de la planilla a partir del querystring:

    - ?desde=YYYY-MM-DD&hasta=YYYY-MM-DD  -> rango libre (hasta inclusive)
    - ?mes=YYYY-MM                        -> ese mes completo
    - sin parámetros                      -> el mes actual

    Devuelve (desde, hasta_exclusivo, contexto_para_el_template).
    """
    from .planilla import rango_mes

    hoy = timezone.localdate()
    desde_txt = (request.GET.get('desde') or '').strip()
    hasta_txt = (request.GET.get('hasta') or '').strip()
    desde = parse_date(desde_txt) if desde_txt else None
    hasta = parse_date(hasta_txt) if hasta_txt else None

    if desde and hasta and desde <= hasta:
        return desde, hasta + datetime.timedelta(days=1), {
            'modo': 'rango',
            'desde': desde,
            'hasta': hasta,
            'mes_valor': hoy.strftime('%Y-%m'),
            'etiqueta': f'{desde:%d/%m/%Y} — {hasta:%d/%m/%Y}',
        }

    mes_txt = (request.GET.get('mes') or '').strip()
    anio, mes = hoy.year, hoy.month
    if mes_txt:
        try:
            anio, mes = (int(p) for p in mes_txt.split('-')[:2])
            datetime.date(anio, mes, 1)
        except (ValueError, TypeError):
            anio, mes = hoy.year, hoy.month

    inicio, fin = rango_mes(anio, mes)
    MESES = [
        '', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
        'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
    ]
    return inicio, fin, {
        'modo': 'mes',
        'desde': inicio,
        'hasta': fin - datetime.timedelta(days=1),
        'mes_valor': f'{anio:04d}-{mes:02d}',
        'etiqueta': f'{MESES[mes]} {anio}',
    }


@login_required
@user_passes_test(es_administrador)
def planilla(request):
    """Planilla del período: todos los empleados activos con su salario
    base, el total de comisiones que ganaron y el total a pagar. Cada fila
    enlaza al detalle de sus comisiones."""
    from .planilla import planilla as calcular_planilla

    desde, hasta, periodo = _periodo_planilla(request)
    usuarios = Usuario.objects.filter(is_active=True).order_by(
        'first_name', 'last_name', 'username',
    )
    filas = calcular_planilla(desde, hasta, usuarios)

    # Solo se puede registrar el pago cuando se está viendo un mes concreto
    # (no un rango de fechas): el pago se guarda por (empleado, mes).
    anio_mes = _mes_del_periodo(periodo)
    if anio_mes:
        pagos = {
            pago.usuario_id: pago
            for pago in PagoPlanilla.objects.filter(
                anio=anio_mes[0], mes=anio_mes[1],
            ).select_related('registrado_por')
        }
        for fila in filas:
            fila['pago'] = pagos.get(fila['usuario'].id)

    totales = {
        'salario_base': sum((f['salario_base'] for f in filas), Decimal('0.00')),
        'comisiones': sum((f['comisiones'] for f in filas), Decimal('0.00')),
        'total': sum((f['total'] for f in filas), Decimal('0.00')),
    }
    return render(request, 'accounts/planilla.html', {
        'filas': filas,
        'totales': totales,
        'periodo': periodo,
        'puede_pagar': anio_mes is not None,
        'query_detalle': request.GET.urlencode(),
    })


def _mes_del_periodo(periodo):
    """(anio, mes) si el período de la planilla es un mes concreto; None si
    es un rango de fechas libre (en ese caso no se registran pagos)."""
    if periodo.get('modo') != 'mes':
        return None
    anio, mes = (int(parte) for parte in periodo['mes_valor'].split('-'))
    return anio, mes


@login_required
@user_passes_test(es_administrador)
def registrar_pago_planilla(request, usuario_id):
    """Registra (o reemplaza) el pago de planilla de un empleado para el mes
    seleccionado, guardando la foto de la boleta / transferencia como
    comprobante."""
    from .planilla import liquidar_lineas, planilla as calcular_planilla

    empleado = get_object_or_404(Usuario, id=usuario_id)
    desde, hasta, periodo = _periodo_planilla(request)
    volver = f"{reverse('planilla')}?{request.GET.urlencode()}"

    anio_mes = _mes_del_periodo(periodo)
    if anio_mes is None:
        messages.error(request, 'Para registrar un pago elija un mes, no un rango de fechas.')
        return redirect(volver)
    anio, mes = anio_mes

    pago = PagoPlanilla.objects.filter(usuario=empleado, anio=anio, mes=mes).first()
    fila = calcular_planilla(desde, hasta, [empleado], pago_a_excluir=pago)[0]

    if request.method == 'POST':
        form = RegistrarPagoPlanillaForm(
            request.POST, request.FILES, monto_esperado=fila['total'],
        )
        if form.is_valid():
            if pago is None:
                pago = PagoPlanilla(usuario=empleado, anio=anio, mes=mes)
            verificacion = form.verificacion
            pago.salario_base = fila['salario_base']
            pago.comisiones = fila['comisiones']
            pago.total = fila['total']
            pago.comprobante = form.cleaned_data['comprobante']
            pago.numero_boleta = form.cleaned_data['numero_boleta']
            pago.notas = form.cleaned_data['notas']
            pago.verificado = bool(verificacion and verificacion.ok)
            pago.verificacion_nota = verificacion.mensaje if verificacion else ''
            pago.registrado_por = request.user
            pago.save()
            # Al reemplazar un pago, se liberan sus comisiones para volver a
            # liquidarlas con los datos actualizados (5C: no cobrar dos veces).
            if pago.pk:
                pago.lineas.all().delete()
            liquidar_lineas(pago, desde, hasta, empleado)
            estado_txt = 'verificado' if pago.verificado else 'SIN verificar'
            Bitacora.registrar(
                request=request, usuario=request.user,
                accion=Bitacora.ACCION_REGISTRAR_PAGO_PLANILLA,
                descripcion=(
                    f'Registró el pago de planilla de "{empleado.username}" — '
                    f'{periodo["etiqueta"]} (Q{pago.total}, {estado_txt}). '
                    f'{pago.verificacion_nota}'
                ),
            )
            if pago.verificado:
                messages.success(
                    request,
                    f'Pago de {periodo["etiqueta"]} registrado y verificado para '
                    f'{empleado.get_full_name() or empleado.username}.',
                )
            else:
                messages.warning(
                    request,
                    f'Pago de {periodo["etiqueta"]} registrado para '
                    f'{empleado.get_full_name() or empleado.username}, pero sin verificar: '
                    f'{pago.verificacion_nota}',
                )
            return redirect(volver)
    else:
        form = RegistrarPagoPlanillaForm(monto_esperado=fila['total'])

    return render(request, 'accounts/registrar_pago_planilla.html', {
        'empleado': empleado,
        'periodo': periodo,
        'fila': fila,
        'pago': pago,
        'form': form,
        'query': request.GET.urlencode(),
    })


@login_required
@user_passes_test(es_administrador)
def planilla_empleado(request, usuario_id):
    """Detalle de las comisiones de un empleado en el período: un resumen
    agrupado (cuántos estudios de cada tipo/horario y a qué %) y el detalle
    línea por línea (fecha, hora, paciente, estudio, comisión)."""
    from .planilla import detalle_empleado

    usuario = get_object_or_404(Usuario, id=usuario_id)
    desde, hasta, periodo = _periodo_planilla(request)
    anio_mes = _mes_del_periodo(periodo)
    pago = None
    if anio_mes:
        pago = PagoPlanilla.objects.filter(
            usuario=usuario, anio=anio_mes[0], mes=anio_mes[1],
        ).first()
    datos = detalle_empleado(desde, hasta, usuario, pago_a_excluir=pago)
    return render(request, 'accounts/planilla_empleado.html', {
        'empleado': usuario,
        'periodo': periodo,
        'query': request.GET.urlencode(),
        **datos,
    })


@login_required
def mi_historial_pagos(request):
    """Historial de los pagos de planilla del empleado autenticado: cada mes
    que le pagaron con su total y un enlace a constancia de su pago."""
    pagos = list(
        request.user.pagos_planilla
        .select_related('registrado_por')
        .order_by('-anio', '-mes')
    )
    return render(request, 'accounts/mi_historial_pagos.html', {
        'pagos': pagos,
    })


def _constancia_puede_ver(request, pago):
    """Solo un administrador o el propio empleado puede ver su constancia."""
    return es_administrador(request.user) or request.user == pago.usuario


@login_required
def constancia_pago_pdf(request, pago_id):
    """Letra / constancia de pago imprimible (PDF) de un PagoPlanilla: datos
    del empleado, período, salario base, comisiones, total, fecha de pago,
    quien lo registró y espacio para firma."""
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    pago = get_object_or_404(
        PagoPlanilla.objects.select_related('usuario', 'registrado_por'), id=pago_id,
    )
    if not _constancia_puede_ver(request, pago):
        return HttpResponseForbidden('No tiene permiso para ver esta constancia.')

    nombre = pago.usuario.get_full_name() or pago.usuario.username
    rol = pago.usuario.get_rol_display()
    titulo_doc = f'CONSTANCIA DE PAGO · {pago.periodo_etiqueta.upper()}'
    cuerpo = [
        Paragraph('CLÍNICA DE IMÁGENES', getSampleStyleSheet()['Title']),
        Paragraph(f'CONSTANCIA DE PAGO DE PLANILLA — {pago.periodo_etiqueta.upper()}',
                  getSampleStyleSheet()['Heading2']),
    ]

    datos = [
        ['Empleado', nombre],
        ['Rol', rol],
        ['Período', pago.periodo_etiqueta],
        ['Salario base', f'Q{pago.salario_base:.2f}'],
        ['Comisiones', f'Q{pago.comisiones:.2f}'],
        ['Total pagado', f'Q{pago.total:.2f}'],
        ['Fecha de pago', _fecha_larga_es(pago.creado_en.date())],
        ['Registrado por', pago.registrado_por.get_full_name() or pago.registrado_por.username],
    ]
    if pago.verificado:
        datos.append(['Verificación', '✓ Comprobante verificado'])
    else:
        datos.append(['Verificación', 'Sin verificar'])

    tabla = Table(datos)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#ede9fe')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    cuerpo.append(Spacer(1, 18))
    cuerpo.append(tabla)

    firma = [Paragraph(
        '<br/><br/><br/>____________________________<br/>'
        f'Firma del empleado · {nombre}',
        getSampleStyleSheet()['BodyText'],
    )]
    tabla_firma = Table([firma], colWidths=[9 * cm])
    tabla_firma.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    cuerpo.append(Spacer(1, 36))
    cuerpo.append(tabla_firma)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    doc.build(cuerpo)

    respuesta = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    nombre_archivo = f'constancia_{pago.periodo_etiqueta.replace(" ", "_")}.pdf'
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return respuesta


@login_required
@user_passes_test(es_administrador)
def editar_usuario(request, usuario_id):
    usuario = get_object_or_404(Usuario, id=usuario_id)
    if request.method == 'POST':
        # Se leen los % de comisión ANTES de validar: form.is_valid() muta la
        # instancia con los datos nuevos.
        comisiones_antes = {
            campo: getattr(usuario, campo) for campo in HistorialComision.CAMPOS_COMISION
        }
        form = EditarUsuarioForm(request.POST, instance=usuario)
        if form.is_valid():
            editado = form.save()
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_EDITAR_USUARIO,
                descripcion=(
                    f'Editó el usuario "{editado.username}" '
                    f'(rol: {editado.get_rol_display()}).'
                ),
            )
            _auditar_cambios_comision(request, editado, comisiones_antes)
            messages.success(request, f'Usuario "{editado.username}" actualizado correctamente.')
            return redirect(_url_lista_para(editado))
    else:
        form = EditarUsuarioForm(instance=usuario)

    contexto = {
        'form': form,
        'usuario_editado': usuario,
        'volver_url': _url_lista_para(usuario),
    }
    if usuario.rol == Usuario.ROL_MEDICO_RADIOLOGO:
        contexto['grupos_estudios'] = _grupos_estudios_para(request, usuario)
    contexto['historial_comisiones'] = usuario.historial_comisiones.select_related(
        'modificado_por'
    )[:10]
    return render(request, 'accounts/editar_usuario.html', contexto)


def _auditar_cambios_comision(request, usuario, comisiones_antes):
    """Registra en HistorialComision + bitácora cada % de comisión que cambió."""
    cambiados = []
    for campo in HistorialComision.CAMPOS_COMISION:
        antes, ahora = comisiones_antes[campo], getattr(usuario, campo)
        if antes != ahora:
            HistorialComision.objects.create(
                usuario=usuario, campo=campo,
                valor_anterior=antes, valor_nuevo=ahora,
                modificado_por=request.user,
            )
            cambiados.append(campo)
    if cambiados:
        detalle = ', '.join(
            f'{HistorialComision.ETIQUETAS_CAMPOS[c]}: '
            f'{comisiones_antes[c]}% → {getattr(usuario, c)}%'
            for c in cambiados
        )
        Bitacora.registrar(
            request=request, usuario=request.user,
            accion=Bitacora.ACCION_EDITAR_COMISION,
            descripcion=f'Cambió comisiones de "{usuario.username}": {detalle}',
        )


@login_required
@user_passes_test(es_administrador)
def historial_comisiones(request):
    """Auditoría de los cambios de % de comisión: fecha, de cuánto a cuánto,
    y qué administrador lo hizo. Filtro por usuario."""
    busqueda = (request.GET.get('q') or '').strip()
    registros = (
        HistorialComision.objects.select_related('usuario', 'modificado_por')
        .order_by('-creado_en')
    )
    if busqueda:
        registros = registros.filter(
            Q(usuario__username__icontains=busqueda)
            | Q(usuario__first_name__icontains=busqueda)
            | Q(usuario__last_name__icontains=busqueda)
        )
    pagina = Paginator(registros, 25).get_page(request.GET.get('page'))
    return render(request, 'accounts/historial_comisiones.html', {
        'pagina': pagina,
        'registros': pagina,
        'busqueda': busqueda,
    })


def _grupos_estudios_para(request, usuario):
    """Tipos de estudio agrupados por modalidad, marcando cuáles tiene
    asignados el radiólogo, para pintar los checkboxes agrupados con
    'seleccionar todo' por grupo en editar_usuario.html."""
    from pacientes.models import TipoEstudio

    if request.method == 'POST':
        seleccionados = set(request.POST.getlist('tipos_estudio'))
    else:
        seleccionados = {str(pk) for pk in usuario.tipos_estudio_asignados.values_list('pk', flat=True)}

    grupos = []
    for slug, etiqueta in TipoEstudio.MODALIDAD_CHOICES:
        estudios = [
            {'id': te.pk, 'nombre': te.nombre, 'marcado': str(te.pk) in seleccionados}
            for te in TipoEstudio.objects.filter(activo=True, modalidad=slug).order_by('nombre')
        ]
        if estudios:
            grupos.append({
                'slug': slug,
                'etiqueta': etiqueta,
                'estudios': estudios,
                'total': len(estudios),
                'marcados': sum(1 for e in estudios if e['marcado']),
            })
    return grupos


@login_required
@user_passes_test(es_administrador)
@require_POST
def cambiar_estado_usuario(request, usuario_id):
    usuario = get_object_or_404(Usuario, id=usuario_id)
    if usuario == request.user:
        messages.error(request, 'No puede cambiar el estado de su propia cuenta.')
    elif usuario.is_superuser:
        messages.error(request, 'No se puede suspender a un superusuario desde esta pantalla.')
    else:
        usuario.is_active = not usuario.is_active
        usuario.save(update_fields=['is_active'])
        verbo = 'reactivó' if usuario.is_active else 'suspendió'
        Bitacora.registrar(
            request=request,
            usuario=request.user,
            accion=Bitacora.ACCION_CAMBIAR_ESTADO_USUARIO,
            descripcion=f'Se {verbo} al usuario "{usuario.username}".',
        )
        messages.success(request, f'Se {verbo} al usuario "{usuario.username}".')
    return redirect(_url_lista_para(usuario))


@login_required
@user_passes_test(es_administrador)
def bitacora(request):
    hoy = datetime.date.today()
    fecha = parse_date(request.GET.get('fecha', '')) or hoy
    if fecha > hoy:
        fecha = hoy

    # No usamos `creado_en__date=fecha`: ese lookup depende de que MySQL
    # tenga cargadas las tablas de zonas horarias con nombre (CONVERT_TZ),
    # y en este servidor no están cargadas, así que Django siempre devolvía
    # 0 filas. Calculamos el rango del día directamente en Python en vez de
    # depender de esa conversión en la base de datos.
    inicio = timezone.make_aware(datetime.datetime.combine(fecha, datetime.time.min))
    fin = timezone.make_aware(datetime.datetime.combine(fecha, datetime.time.max))
    eventos_qs = (
        Bitacora.objects.filter(creado_en__range=(inicio, fin))
        .select_related('usuario')
        .order_by('-creado_en')
    )

    filtro_accion = (request.GET.get('accion') or '').strip()
    filtro_usuario = (request.GET.get('usuario') or '').strip()
    busqueda = (request.GET.get('q') or '').strip()
    if filtro_accion in dict(Bitacora.ACCION_CHOICES):
        eventos_qs = eventos_qs.filter(accion=filtro_accion)
    if filtro_usuario.isdigit():
        eventos_qs = eventos_qs.filter(usuario_id=filtro_usuario)
    if busqueda:
        eventos_qs = eventos_qs.filter(descripcion__icontains=busqueda)

    pagina = Paginator(eventos_qs, 25).get_page(request.GET.get('page'))

    # Solo se mantienen en los links de paginación los filtros no vacíos.
    filtros_activos = {
        clave: valor for clave, valor in (
            ('accion', filtro_accion), ('usuario', filtro_usuario), ('q', busqueda),
        ) if valor
    }
    querystring_filtros = urlencode(filtros_activos)

    return render(request, 'accounts/bitacora.html', {
        'eventos': pagina,
        'pagina': pagina,
        'fecha': fecha,
        'hoy': hoy,
        'dia_anterior': fecha - datetime.timedelta(days=1),
        'dia_siguiente': fecha + datetime.timedelta(days=1),
        'puede_avanzar': fecha < hoy,
        'acciones': Bitacora.ACCION_CHOICES,
        'usuarios': Usuario.objects.order_by('username'),
        'filtro_accion': filtro_accion,
        'filtro_usuario': filtro_usuario,
        'busqueda': busqueda,
        'querystring_filtros': querystring_filtros,
    })
