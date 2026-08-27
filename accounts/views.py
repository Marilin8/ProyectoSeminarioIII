import datetime

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from .forms import CambiarContrasenaForm, CrearUsuarioForm, EditarUsuarioForm, PerfilForm
from .models import Bitacora, Usuario
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
        form = EditarUsuarioForm(request.POST, instance=usuario)
        if form.is_valid():
            form.save()
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_EDITAR_USUARIO,
                descripcion=(
                    f'Editó el usuario "{usuario.username}" '
                    f'(rol: {usuario.get_rol_display()}).'
                ),
            )
            messages.success(request, f'Usuario "{usuario.username}" actualizado correctamente.')
            return redirect(_url_lista_para(usuario))
    else:
        form = EditarUsuarioForm(instance=usuario)

    contexto = {
        'form': form,
        'usuario_editado': usuario,
        'volver_url': _url_lista_para(usuario),
    }
    if usuario.rol == Usuario.ROL_MEDICO_RADIOLOGO:
        contexto['grupos_estudios'] = _grupos_estudios_para(request, usuario)
    return render(request, 'accounts/editar_usuario.html', contexto)


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
