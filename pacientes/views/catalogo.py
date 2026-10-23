"""Catálogo de estudios: modalidades, tipos de estudio, precios y combos.

Los precios se guardan en la matriz ``PrecioEstudio`` (convenio × horario
hábil/inhábil, por sucursal) y cada cambio queda en ``HistorialPrecioEstudio``
para que los reportes viejos sigan saliendo con el precio de su fecha.
"""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from accounts import sucursales
from accounts.models import Bitacora
from accounts.views import es_administrador

from ..forms import (
    ComboForm,
    CrearTipoEstudioForm,
    FechaVigenciaProgramadaForm,
    PreciosSucursalForm,
)
from ..models import (
    CambioEstudioProgramado,
    Cita,
    Combo,
    HistorialModalidad,
    HistorialPrecioEstudio,
    Modalidad,
    PrecioEstudio,
    TipoEstudio,
)


@login_required
@user_passes_test(es_administrador)
def crear_estudio(request):
    """Alta de un tipo de estudio con su modalidad, duración y matriz de precios
    (``CrearTipoEstudioForm`` guarda también los ``PrecioEstudio``)."""
    if request.method == 'POST':
        form = CrearTipoEstudioForm(request.POST)
        if form.is_valid():
            tipo_estudio = form.save()
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_CREAR_ESTUDIO,
                descripcion=(
                    f'Creó el estudio "{tipo_estudio.nombre}" '
                    f'({tipo_estudio.get_modalidad_display()}, {tipo_estudio.duracion_minutos} min).'
                ),
            )
            messages.success(request, f'Estudio "{tipo_estudio.nombre}" creado correctamente.')
            return redirect('dashboard')
    else:
        form = CrearTipoEstudioForm()
    return render(request, 'pacientes/crear_estudio.html', {'form': form, 'editando': None})


@login_required
@user_passes_test(es_administrador)
def lista_modalidades(request):
    """Listado de modalidades (RX, USG, TAC...) con búsqueda por nombre."""
    busqueda = (request.GET.get('q') or '').strip()

    modalidades = Modalidad.objects.all().order_by('nombre')

    if busqueda:
        modalidades = modalidades.filter(nombre__icontains=busqueda)

    return render(request, 'pacientes/lista_modalidades.html', {
        'modalidades': modalidades,
        'busqueda': busqueda,
    })


@login_required
@user_passes_test(es_administrador)
def crear_modalidad(request):
    """Crea una modalidad. El ``codigo`` interno se genera con slugify del nombre
    y se le agrega un sufijo _2, _3... si ya existe. Queda en el historial."""
    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()

        if not nombre:
            messages.error(request, 'Escriba el nombre de la modalidad.')
        elif Modalidad.objects.filter(nombre__iexact=nombre).exists():
            messages.error(request, 'Ya existe una modalidad con ese nombre.')
        else:
            base_codigo = slugify(nombre).replace('-', '_')[:30] or 'modalidad'
            codigo = base_codigo
            contador = 2

            while Modalidad.objects.filter(codigo=codigo).exists():
                sufijo = f'_{contador}'
                codigo = f'{base_codigo[:30-len(sufijo)]}{sufijo}'
                contador += 1

            modalidad = Modalidad.objects.create(
                nombre=nombre,
                codigo=codigo,
            )

            HistorialModalidad.objects.create(
                modalidad=modalidad,
                nombre=modalidad.nombre,
                nombre_anterior='',
                accion=HistorialModalidad.ACCION_CREAR,
                realizado_por=request.user,
            )

            messages.success(
                request,
                f'Modalidad "{modalidad.nombre}" creada correctamente.'
            )
            return redirect('lista_modalidades')

    return render(request, 'pacientes/crear_modalidad.html', {
        'editando': None,
    })


@login_required
@user_passes_test(es_administrador)
def editar_modalidad(request, modalidad_id):
    """Renombra una modalidad (sin repetir nombres) y registra el cambio en el historial."""
    modalidad = get_object_or_404(Modalidad, id=modalidad_id)

    if request.method == 'POST':
        nombre_nuevo = (request.POST.get('nombre') or '').strip()

        if not nombre_nuevo:
            messages.error(request, 'Escriba el nombre de la modalidad.')

        elif (
            Modalidad.objects
            .filter(nombre__iexact=nombre_nuevo)
            .exclude(id=modalidad.id)
            .exists()
        ):
            messages.error(request, 'Ya existe otra modalidad con ese nombre.')

        elif nombre_nuevo != modalidad.nombre:
            nombre_anterior = modalidad.nombre

            modalidad.nombre = nombre_nuevo
            modalidad.save(update_fields=['nombre', 'actualizado_en'])

            HistorialModalidad.objects.create(
                modalidad=modalidad,
                nombre=modalidad.nombre,
                nombre_anterior=nombre_anterior,
                accion=HistorialModalidad.ACCION_EDITAR,
                realizado_por=request.user,
            )

            messages.success(
                request,
                f'Modalidad "{modalidad.nombre}" actualizada correctamente.'
            )
            return redirect('lista_modalidades')

        else:
            messages.info(request, 'No se realizaron cambios.')
            return redirect('lista_modalidades')

    return render(request, 'pacientes/crear_modalidad.html', {
        'editando': modalidad,
        'modalidad': modalidad,
    })


@login_required
@user_passes_test(es_administrador)
@require_POST
def eliminar_modalidad(request, modalidad_id):
    """Baja lógica: la modalidad queda inactiva (no se borra, la usan estudios
    y citas viejas) y se anota en el historial."""
    modalidad = get_object_or_404(Modalidad, id=modalidad_id)
    nombre = modalidad.nombre

    HistorialModalidad.objects.create(
        modalidad=modalidad,
        nombre=nombre,
        nombre_anterior=nombre,
        accion=HistorialModalidad.ACCION_ELIMINAR,
        realizado_por=request.user,
    )

    modalidad.activo = False
    modalidad.save(update_fields=['activo', 'actualizado_en'])

    messages.success(
        request,
        f'Modalidad "{nombre}" desactivada correctamente.'
    )

    return redirect('lista_modalidades')


@login_required
@user_passes_test(es_administrador)
@require_POST
def activar_modalidad(request, modalidad_id):
    """Vuelve a activar una modalidad desactivada."""
    modalidad = get_object_or_404(Modalidad, id=modalidad_id)

    modalidad.activo = True
    modalidad.save(update_fields=['activo', 'actualizado_en'])

    messages.success(
        request,
        f'Modalidad "{modalidad.nombre}" activada correctamente.'
    )

    return redirect('lista_modalidades')


@login_required
@user_passes_test(es_administrador)
def historial_modalidades(request):
    """Historial paginado de altas, cambios de nombre y bajas de modalidades."""
    busqueda = (request.GET.get('q') or '').strip()

    registros = (
        HistorialModalidad.objects
        .select_related('realizado_por')
        .order_by('-creado_en')
    )

    if busqueda:
        registros = registros.filter(
            Q(nombre__icontains=busqueda)
            | Q(nombre_anterior__icontains=busqueda)
        )

    pagina = Paginator(registros, 25).get_page(request.GET.get('page'))

    return render(request, 'pacientes/historial_modalidades.html', {
        'pagina': pagina,
        'registros': pagina,
        'busqueda': busqueda,
    })


ESTUDIOS_POR_PAGINA = 20


@login_required
@user_passes_test(es_administrador)
def lista_estudios(request):
    """Catálogo paginado de tipos de estudio con filtro por nombre y modalidad."""
    busqueda = (request.GET.get('q') or '').strip()
    modalidad = (request.GET.get('modalidad') or '').strip()

    estudios = TipoEstudio.objects.all().prefetch_related('precios').order_by('modalidad', 'nombre')
    if busqueda:
        estudios = estudios.filter(nombre__icontains=busqueda)
    if modalidad in dict(TipoEstudio.MODALIDAD_CHOICES):
        estudios = estudios.filter(modalidad=modalidad)

    pagina = Paginator(estudios, ESTUDIOS_POR_PAGINA).get_page(request.GET.get('page'))

    filtros = request.GET.copy()
    filtros.pop('page', None)
    return render(request, 'pacientes/lista_estudios.html', {
        'estudios': pagina,
        'pagina': pagina,
        'busqueda': busqueda,
        'modalidad': modalidad,
        'modalidades': TipoEstudio.MODALIDAD_CHOICES,
        'filtros_qs': filtros.urlencode(),
    })


@login_required
@user_passes_test(es_administrador)
def editar_estudio(request, estudio_id):
    """Edita un tipo de estudio y su matriz de precios general. Antes de guardar
    copia los precios anteriores para auditar cada celda que cambió
    (``_auditar_cambios_precio`` -> HistorialPrecioEstudio)."""
    tipo_estudio = get_object_or_404(TipoEstudio, id=estudio_id)
    if request.method == 'POST':
        # Se lee ANTES de guardar: form.save() ya deja la matriz de precios
        # actualizada (ver CrearTipoEstudioForm.save), así que después no
        # hay forma de saber qué valor tenía cada celda.
        precios_antes = {
            (p.convenio, p.horario_habil): p.precio for p in tipo_estudio.precios.all() if p.sucursal_id is None
        }
        form = CrearTipoEstudioForm(request.POST, instance=tipo_estudio)
        if form.is_valid():
            tipo_estudio = form.save()
            _auditar_cambios_precio(request, tipo_estudio, precios_antes)
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_EDITAR_ESTUDIO,
                descripcion=(
                    f'Editó el estudio "{tipo_estudio.nombre}" '
                    f'({tipo_estudio.get_modalidad_display()}, {tipo_estudio.duracion_minutos} min).'
                ),
            )
            messages.success(request, f'Estudio "{tipo_estudio.nombre}" actualizado correctamente.')
            return redirect('lista_estudios')
    else:
        form = CrearTipoEstudioForm(instance=tipo_estudio)
    return render(request, 'pacientes/crear_estudio.html', {
        'form': form,
        'editando': tipo_estudio,
        'historial_precios': tipo_estudio.historial_precios.filter(sucursal__isnull=True)
        .select_related('modificado_por')[:10],
        'cambios_programados': tipo_estudio.cambios_programados.filter(
            estado=CambioEstudioProgramado.ESTADO_PENDIENTE,
        ).select_related('creado_por'),
    })


@login_required
@user_passes_test(es_administrador)
@require_POST
def programar_cambio_estudio(request, estudio_id):
    """El administrador arma el estudio como quedaría (nombre, modalidad,
    duración y precios) con el mismo formulario que la edición inmediata,
    pero en vez de guardar ahora, programa que se aplique solo desde cierta
    fecha (ver CambioEstudioProgramado)."""
    tipo_estudio = get_object_or_404(TipoEstudio, id=estudio_id)
    form = CrearTipoEstudioForm(request.POST, instance=tipo_estudio)
    fecha_form = FechaVigenciaProgramadaForm(request.POST)
    if not form.is_valid() or not fecha_form.is_valid():
        for f in (form, fecha_form):
            for errores in f.errors.values():
                for error in errores:
                    messages.error(request, error)
        return redirect('editar_estudio', estudio_id=tipo_estudio.id)

    # form.save(commit=False) deja los valores nuevos en el objeto EN
    # MEMORIA (nombre/modalidad/duración) sin tocar la base de datos -- ni
    # siquiera guarda_precios() corre con commit=False -- así que el
    # estudio real sigue exactamente igual hasta que llegue la fecha.
    propuesto = form.save(commit=False)
    cambio = CambioEstudioProgramado.objects.create(
        tipo_estudio=tipo_estudio,
        nombre=propuesto.nombre,
        modalidad=propuesto.modalidad,
        duracion_minutos=propuesto.duracion_minutos,
        precio_coex_habil=form.cleaned_data['precio_coex_habil'],
        precio_privado_habil=form.cleaned_data['precio_privado_habil'],
        precio_privado_inhabil=form.cleaned_data['precio_privado_inhabil'],
        precio_emergencia_igss_habil=form.cleaned_data['precio_emergencia_igss_habil'],
        precio_emergencia_igss_inhabil=form.cleaned_data['precio_emergencia_igss_inhabil'],
        fecha_vigencia=fecha_form.cleaned_data['fecha_vigencia'],
        creado_por=request.user,
    )
    detalle = '; '.join(cambio.resumen_diferencias()) or 'sin cambios respecto al valor actual'
    Bitacora.registrar(
        request=request, usuario=request.user,
        accion=Bitacora.ACCION_PROGRAMAR_CAMBIO_PRECIO,
        descripcion=(
            f'Programó cambios en el estudio "{tipo_estudio.nombre}" desde el '
            f'{cambio.fecha_vigencia:%d/%m/%Y}: {detalle}.'
        ),
    )
    messages.success(
        request,
        f'Cambios programados para "{tipo_estudio.nombre}" a partir del '
        f'{cambio.fecha_vigencia:%d/%m/%Y}.',
    )
    return redirect('editar_estudio', estudio_id=tipo_estudio.id)


@login_required
@user_passes_test(es_administrador)
@require_POST
def cancelar_cambio_estudio_programado(request, cambio_id):
    """Cancela un cambio de estudio programado que todavía no se aplicó."""
    cambio = get_object_or_404(
        CambioEstudioProgramado, id=cambio_id, estado=CambioEstudioProgramado.ESTADO_PENDIENTE,
    )
    cambio.estado = CambioEstudioProgramado.ESTADO_CANCELADO
    cambio.cancelado_por = request.user
    cambio.cancelado_en = timezone.now()
    cambio.save(update_fields=['estado', 'cancelado_por', 'cancelado_en'])
    Bitacora.registrar(
        request=request, usuario=request.user,
        accion=Bitacora.ACCION_CANCELAR_CAMBIO_PRECIO,
        descripcion=f'Canceló el cambio programado del estudio "{cambio.tipo_estudio.nombre}".',
    )
    messages.success(request, 'Cambio programado cancelado.')
    return redirect('editar_estudio', estudio_id=cambio.tipo_estudio_id)


def _auditar_cambios_precio(request, tipo_estudio, precios_antes):
    """Registra en HistorialPrecioEstudio + bitácora cada celda de la
    matriz de precios que cambió (mismo patrón que
    accounts.views._auditar_cambios_comision, para precios de estudio)."""
    cambiados = []
    precios_ahora = {
        (p.convenio, p.horario_habil): p.precio for p in tipo_estudio.precios.all() if p.sucursal_id is None
    }
    for (convenio, habil), ahora in precios_ahora.items():
        antes = precios_antes.get((convenio, habil), Decimal('0.00'))
        if antes != ahora:
            HistorialPrecioEstudio.objects.create(
                tipo_estudio=tipo_estudio, convenio=convenio, horario_habil=habil,
                valor_anterior=antes, valor_nuevo=ahora,
                modificado_por=request.user,
            )
            cambiados.append((convenio, habil, antes, ahora))
    if cambiados:
        nombres_convenio = dict(Cita.CONVENIO_CHOICES)
        detalle = ', '.join(
            f'{nombres_convenio.get(c, c)} {"hábil" if h else "inhábil"}: Q{a} → Q{n}'
            for c, h, a, n in cambiados
        )
        Bitacora.registrar(
            request=request, usuario=request.user,
            accion=Bitacora.ACCION_EDITAR_PRECIO_ESTUDIO,
            descripcion=f'Cambió precios de "{tipo_estudio.nombre}": {detalle}',
        )


@login_required
@user_passes_test(es_administrador)
def precios_sucursal_estudio(request, estudio_id):
    """Precios propios de una sucursal para un estudio. Lo que se deja vacío usa el
    precio general. Cada cambio queda en HistorialPrecioEstudio (con la sucursal), así
    los reportes y boletas de fechas pasadas siguen mostrando el precio de ese día."""
    from accounts.models import Sucursal
    estudio = get_object_or_404(TipoEstudio.objects.prefetch_related('precios'), id=estudio_id)
    opciones = list(Sucursal.objects.filter(activa=True))
    elegida_id = request.POST.get('sucursal') or request.GET.get('sucursal')
    sucursal = next((s for s in opciones if str(s.id) == str(elegida_id)), None)
    if sucursal is None:
        sucursal = sucursales.sucursal_activa(request) or (opciones[0] if opciones else None)
    if sucursal is None:
        messages.error(request, 'Primero cree una sucursal.')
        return redirect('lista_sucursales')

    form = PreciosSucursalForm(request.POST or None, estudio=estudio, sucursal=sucursal)
    if request.method == 'POST' and form.is_valid():
        cambios = _guardar_precios_sucursal(request, estudio, sucursal, form)
        if cambios:
            nombres = dict(Cita.CONVENIO_CHOICES)
            Bitacora.registrar(
                request=request, usuario=request.user, accion=Bitacora.ACCION_EDITAR_PRECIO_ESTUDIO,
                descripcion=(
                    f'Cambió precios de "{estudio.nombre}" en la sucursal {sucursal.nombre}: '
                    + ', '.join(
                        f'{nombres.get(c, c)} {"hábil" if h else "inhábil"}: '
                        f'{"general" if a is None else f"Q{a}"} → {"general" if n is None else f"Q{n}"}'
                        for c, h, a, n in cambios
                    )
                ),
            )
            for combo in estudio.combos.all():
                combo.sincronizar_tipo_estudio()
            messages.success(request, f'Precios de "{estudio.nombre}" en {sucursal.nombre} guardados.')
        else:
            messages.info(request, 'No hubo cambios.')
        return redirect(f"{reverse('precios_sucursal_estudio', args=[estudio.id])}?sucursal={sucursal.id}")

    return render(request, 'pacientes/precios_sucursal_estudio.html', {
        'estudio': estudio,
        'sucursal': sucursal,
        'sucursales_opciones': opciones,
        'form': form,
        'historial': estudio.historial_precios.filter(sucursal=sucursal).select_related('modificado_por')[:15],
    })


def _guardar_precios_sucursal(request, estudio, sucursal, form):
    """Crea, cambia o quita los precios propios de la sucursal y deja el rastro.
    Devuelve [(convenio, hábil, antes, después)] con None = precio general."""
    cambios = []
    with transaction.atomic():
        actuales = {
            (p.convenio, p.horario_habil): p
            for p in PrecioEstudio.objects.select_for_update().filter(tipo_estudio=estudio, sucursal=sucursal)
        }
        for campo, convenio, habil, _etiqueta, _general in form.celdas:
            nuevo = form.cleaned_data.get(campo)
            fila = actuales.get((convenio, habil))
            antes = fila.precio if fila else None
            if nuevo == antes:
                continue
            if nuevo is None:
                fila.delete()
            elif fila is None:
                PrecioEstudio.objects.create(
                    tipo_estudio=estudio, convenio=convenio, horario_habil=habil, sucursal=sucursal, precio=nuevo,
                )
            else:
                fila.precio = nuevo
                fila.save(update_fields=['precio'])
            HistorialPrecioEstudio.objects.create(
                tipo_estudio=estudio, convenio=convenio, horario_habil=habil, sucursal=sucursal,
                valor_anterior=antes, valor_nuevo=nuevo, modificado_por=request.user,
            )
            cambios.append((convenio, habil, antes, nuevo))
    return cambios


@login_required
@user_passes_test(es_administrador)
def historial_precios_estudio(request):
    """Auditoría de los cambios de precio de estudios: fecha, de cuánto a
    cuánto, y qué administrador lo hizo. Filtro por nombre del estudio."""
    busqueda = (request.GET.get('q') or '').strip()
    registros = (
        HistorialPrecioEstudio.objects.select_related('tipo_estudio', 'modificado_por', 'sucursal')
        .order_by('-creado_en')
    )
    if busqueda:
        registros = registros.filter(tipo_estudio__nombre__icontains=busqueda)
    pagina = Paginator(registros, 25).get_page(request.GET.get('page'))
    return render(request, 'pacientes/historial_precios_estudio.html', {
        'pagina': pagina,
        'registros': pagina,
        'busqueda': busqueda,
    })


@login_required
@user_passes_test(es_administrador)
def lista_combos(request):
    """Catálogo de combos de estudios (ver pacientes.models.Combo): se
    administra íntegro desde acá, igual que Estudios (lista_estudios).
    Portado (2026-09-04) desde la rama visual-andres de TechBlood — ahí
    esta pantalla estaba abierta a cualquier recepcionista pero solo
    aparecía en el menú del administrador; se corrige ese permiso
    inconsistente al portarla."""
    combos = Combo.objects.all().prefetch_related('estudios').order_by('nombre')
    return render(request, 'pacientes/lista_combos.html', {'combos': combos})


def _avisar_si_combo_sin_radiologo_en_comun(request, combo, tipo_estudio):
    """El espejo del combo (ver Combo.sincronizar_tipo_estudio) solo queda
    con radiólogo para elegir al agendar si hay al menos uno que haga TODOS
    sus estudios. Si la intersección quedó vacía, se avisa -- el combo se
    crea/edita igual, solo que no se va a poder asignar radiólogo al
    agendarlo hasta que se corrija."""
    if combo.estudios.exists() and not tipo_estudio.radiologos.exists():
        messages.warning(
            request,
            f'Ningún radiólogo hace todos los estudios de "{combo.nombre}": no vas a poder '
            'asignarle uno al agendarlo. Revisá los radiólogos asignados a cada estudio '
            'del combo (Estudios) para que al menos uno cubra todos.',
        )


@login_required
@user_passes_test(es_administrador)
def crear_combo(request):
    """Crea un combo (varios estudios que se cobran juntos) y sincroniza el
    TipoEstudio que lo representa en la agenda. Avisa si los estudios no
    tienen ningún radiólogo en común."""
    if request.method == 'POST':
        form = ComboForm(request.POST)
        if form.is_valid():
            combo = form.save()
            tipo_estudio = combo.sincronizar_tipo_estudio()
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_CREAR_COMBO,
                descripcion=f'Creó el combo "{combo.nombre}" con {combo.estudios.count()} estudios.',
            )
            messages.success(request, f'Combo "{combo.nombre}" creado correctamente.')
            _avisar_si_combo_sin_radiologo_en_comun(request, combo, tipo_estudio)
            return redirect('lista_combos')
    else:
        form = ComboForm()
    return render(request, 'pacientes/crear_combo.html', {'form': form, 'editando': None})


@login_required
@user_passes_test(es_administrador)
def editar_combo(request, combo_id):
    """Edita un combo y vuelve a sincronizar su TipoEstudio generado."""
    combo = get_object_or_404(Combo, id=combo_id)
    if request.method == 'POST':
        form = ComboForm(request.POST, instance=combo)
        if form.is_valid():
            combo = form.save()
            tipo_estudio = combo.sincronizar_tipo_estudio()
            Bitacora.registrar(
                request=request,
                usuario=request.user,
                accion=Bitacora.ACCION_EDITAR_COMBO,
                descripcion=f'Editó el combo "{combo.nombre}".',
            )
            messages.success(request, f'Combo "{combo.nombre}" actualizado correctamente.')
            _avisar_si_combo_sin_radiologo_en_comun(request, combo, tipo_estudio)
            return redirect('lista_combos')
    else:
        form = ComboForm(instance=combo)
    return render(request, 'pacientes/crear_combo.html', {'form': form, 'editando': combo})
