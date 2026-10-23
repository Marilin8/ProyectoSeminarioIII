"""Vistas de la app ``pacientes``, separadas por responsabilidad.

Este paquete reemplaza al antiguo ``pacientes/views.py`` (más de 6000 líneas).
``urls.py`` sigue usando ``views.<nombre>``: aquí se reexportan las vistas que
tienen URL. Para importar un helper interno, importalo desde su módulo
(p. ej. ``from pacientes.views.envio_resultados import _cobro_bloquea_envio``).

Módulos:
  permisos           funciones de rol para ``@user_passes_test``
  avisos             creación de notificaciones internas por cada paso del flujo
  comun              datos fijos de la clínica para boletas y PDFs
  pacientes          búsqueda, historial y contacto de pacientes
  citas              agenda, agendar cita, confirmación del radiólogo, llegada, orden
  turnos             sala de espera, tickets y emergencias
  estudios           técnico/radiólogo: imágenes, verificación, informe
  envio_resultados   envío de resultados por correo/QR
  caja               cobros, órdenes de pago, boletas y pagos IGSS
  catalogo           modalidades, estudios, precios y combos
  medicos_tratantes  médicos tratantes y comisiones
  reportes           reportes diarios (PDF/Excel) e informe anual
  notificaciones     endpoints de la campanita
  visor              visor web de estudios (paciente y médico con OTP)
  agente             API del agente que borra en las PCs lo ya subido
"""
from .pacientes import (  # noqa: F401
    buscar_paciente_por_dpi,
    buscar_paciente_por_telefono,
    completar_datos_paciente,
    editar_contacto_paciente,
    historial_paciente,
    historial_pacientes,
    radiologos_por_estudio,
    ver_estudio_historial,
)
from .citas import (  # noqa: F401
    agendar_cita,
    agendar_cita_privado,
    confirmar_reagenda,
    eliminar_cita,
    generar_orden,
    marcar_ausente,
    marcar_llegada,
    procesar_citas,
    revisar_solicitud,
    seleccionar_horario,
    solicitudes_pendientes,
)
from .turnos import (  # noqa: F401
    avanzar_turno,
    eliminar_turno,
    estado_sala_espera,
    mover_turno,
    pantalla_sala_espera,
    pantalla_turnos,
    procesar_ticket_emergencia,
    procesar_turno,
    reagendar_desde_turno,
    registrar_ticket_emergencia,
)
from .estudios import (  # noqa: F401
    adjuntar_imagenes,
    adjuntar_imagenes_finalizar,
    adjuntar_imagenes_lote,
    adjuntar_informe,
    agregar_estudio_extra,
    citas_procesadas,
    corregir_estudio_cita,
    descargar_dicom_orden,
    estudios_por_corregir,
    guardar_seleccion_imagenes,
    ordenes_pendientes,
    validar_estudio,
    ver_imagenes_jpg,
)
from .envio_resultados import (  # noqa: F401
    enviar_estudio,
    ingresar_correo_envio,
    qr_estudio,
)
from .caja import (  # noqa: F401
    boleta_pago_pdf,
    comprobante_bancario,
    constancia_firmada,
    constancia_pago_pdf,
    crear_orden_pago,
    marcar_cobrado,
    orden_pago_pdf,
    pagar_orden_pago,
    pagos_pendientes,
    pagos_pendientes_igss,
    subir_constancia_firmada,
)
from .catalogo import (  # noqa: F401
    activar_modalidad,
    cancelar_cambio_estudio_programado,
    crear_combo,
    crear_estudio,
    crear_modalidad,
    editar_combo,
    editar_estudio,
    editar_modalidad,
    eliminar_modalidad,
    historial_modalidades,
    historial_precios_estudio,
    lista_combos,
    lista_estudios,
    lista_modalidades,
    precios_sucursal_estudio,
    programar_cambio_estudio,
)
from .medicos_tratantes import (  # noqa: F401
    activar_medico_tratante,
    comision_medico_tratante_pdf,
    crear_medico_tratante,
    editar_medico_tratante,
    eliminar_medico_tratante,
    lista_medicos_tratantes,
    reporte_comision_medico_tratante,
)
from .reportes import (  # noqa: F401
    descargar_reporte_pdf,
    descargar_reporte_xlsx,
    enviar_reporte_diario,
    firma_reporte_diario,
    informe_anual,
    lista_reportes_diarios,
    ver_reporte_diario,
)
from .notificaciones import (  # noqa: F401
    marcar_notificacion_leida,
    marcar_notificaciones_leidas,
    notificaciones_pendientes,
)
from .visor import (  # noqa: F401
    visor_dicom,
    visor_estudio,
    visor_estudio_historial,
    visor_estudio_medico_tratante,
    visor_imagen,
    visor_informe_pdf,
    visor_jpg,
)
from .agente import (  # noqa: F401
    confirmar_huellas,
)
