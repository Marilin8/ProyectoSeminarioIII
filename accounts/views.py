<<<<<<< HEAD
import base64
import datetime
import io

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
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
)
from .models import Bitacora, HistorialComision, Usuario
=======
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from .forms import CrearUsuarioForm
from .models import Bitacora, Usuario
>>>>>>> 6c6a7f92a98d42c5c4312897e77c9a819885bb58
from .pantallas import buscar_pantalla, pantallas_de


def es_administrador(user):
    return user.is_authenticated and (user.is_superuser or user.rol == Usuario.ROL_ADMINISTRADOR)


<<<<<<< HEAD
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


=======
>>>>>>> 6c6a7f92a98d42c5c4312897e77c9a819885bb58
@login_required
def dashboard(request):
    return render(request, 'accounts/dashboard.html', {'pantallas': pantallas_de(request.user)})


@login_required
<<<<<<< HEAD
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
=======
>>>>>>> 6c6a7f92a98d42c5c4312897e77c9a819885bb58
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
<<<<<<< HEAD
def lista_usuarios(request, rol):
    if rol not in ROLES_GESTIONABLES:
        raise Http404
    usuarios = Usuario.objects.filter(rol=rol).order_by('-is_active', 'first_name', 'last_name', 'username')
    if rol == Usuario.ROL_MEDICO_RADIOLOGO:
        usuarios = usuarios.prefetch_related('tipos_estudio_asignados')
    return render(request, 'accounts/lista_usuarios.html', {
        'usuarios': usuarios,
        'rol': rol,
        'rol_label': ROLES_GESTIONABLES[rol],
        'es_radiologo': rol == Usuario.ROL_MEDICO_RADIOLOGO,
        'roles_gestionables': ROLES_GESTIONABLES,
    })


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
        messages.error(request, 'No podés cambiar el estado de tu propia cuenta.')
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
=======
>>>>>>> 6c6a7f92a98d42c5c4312897e77c9a819885bb58
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
<<<<<<< HEAD
    eventos_qs = (
=======
    eventos = (
>>>>>>> 6c6a7f92a98d42c5c4312897e77c9a819885bb58
        Bitacora.objects.filter(creado_en__range=(inicio, fin))
        .select_related('usuario')
        .order_by('-creado_en')
    )
<<<<<<< HEAD

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
=======
    return render(request, 'accounts/bitacora.html', {
        'eventos': eventos,
>>>>>>> 6c6a7f92a98d42c5c4312897e77c9a819885bb58
        'fecha': fecha,
        'hoy': hoy,
        'dia_anterior': fecha - datetime.timedelta(days=1),
        'dia_siguiente': fecha + datetime.timedelta(days=1),
        'puede_avanzar': fecha < hoy,
<<<<<<< HEAD
        'acciones': Bitacora.ACCION_CHOICES,
        'usuarios': Usuario.objects.order_by('username'),
        'filtro_accion': filtro_accion,
        'filtro_usuario': filtro_usuario,
        'busqueda': busqueda,
        'querystring_filtros': querystring_filtros,
=======
>>>>>>> 6c6a7f92a98d42c5c4312897e77c9a819885bb58
    })
