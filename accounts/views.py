import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from .forms import CrearUsuarioForm
from .models import Bitacora, Usuario
from .pantallas import buscar_pantalla, pantallas_de


def es_administrador(user):
    return user.is_authenticated and (user.is_superuser or user.rol == Usuario.ROL_ADMINISTRADOR)


@login_required
def dashboard(request):
    return render(request, 'accounts/dashboard.html', {'pantallas': pantallas_de(request.user)})


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
    eventos = (
        Bitacora.objects.filter(creado_en__range=(inicio, fin))
        .select_related('usuario')
        .order_by('-creado_en')
    )
    return render(request, 'accounts/bitacora.html', {
        'eventos': eventos,
        'fecha': fecha,
        'hoy': hoy,
        'dia_anterior': fecha - datetime.timedelta(days=1),
        'dia_siguiente': fecha + datetime.timedelta(days=1),
        'puede_avanzar': fecha < hoy,
    })
