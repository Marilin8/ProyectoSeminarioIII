# HU-58 y correcciones COEX, IGSS

## Descripción

Se implementó la **HU-058: Cobro e Integración de Estudios Extra y Combos**, junto con las correcciones solicitadas para el flujo de cobro de **COEX** y **Emergencia IGSS**.

El objetivo principal es evitar que los estudios adicionales queden sin cobrar, permitir la creación de órdenes de pago agrupadas y bloquear la entrega de resultados mientras existan saldos pendientes.

## Funcionalidades agregadas para HU-058

- Registro de estudios extra realizados por Radiología.
- Notificación automática a Recepción/Caja cuando se agrega un estudio extra.
- Reapertura del cobro cuando se agrega un estudio extra después de haber pagado el estudio original.
- Creación de órdenes de pago agrupadas.
- Asociación de varias citas a una misma orden de pago.
- Validación para que una orden agrupada solo incluya:
  - Estudios del mismo paciente.
  - Estudios del mismo convenio.
  - Estudios con cobro pendiente.
- Aplicación de combos con descuento.
- Cálculo automático de:
  - Subtotal.
  - Descuento.
  - Total final.
- Resumen visual antes de crear una orden :
  - Estudios seleccionados.
  - Paciente.
  - Convenio.
  - Subtotal.
  - Descuento.
  - Total.
- Confirmación visual antes de crear la orden.
- Registro de:
  - Forma de pago.
  - Número de boleta o referencia.
  - Boleta bancaria global.
  - Usuario que confirmp Cl pago.
  - Fecha de confirmación.
  - Notas de la orden.
- Propagación de la boleta global a los cobrm� individuales relacionados.
- Generación y consulta de recibos internos.
- Generación y consulta de constancias internas.
- Posibilidad de cargar constancias firmadas.
- Bloqueo financiero

1. Abrir el historial de pacientes:

```text
http://127.0.0.1:8000/pacientes/historial/
```

2. Buscar un paciente COEX o Emergencia IGSS.
3. Abrir sus estudios.
4. Filtrar por:

```text
Estado de pago: Pendiente
```

5. Intentar enviar el estudio.

Resultado esperado:

- El envío está bloqueado.
- Se muestra el mensaje de cobro pendiente.
- El botón de envío aparece deshabilitado o la operación es rechazada.

Después:

1. Ir a Caja.
2. Confirmar la orden agrupada"
3. Regresar al historial.
4. Actualizar la página.
5. Filtrar por:

```text
Estado de pago: Pagado
```

6. Intentar enviar nuevamente el estudio.

Resultado esperado:

- El cobro se registra individualmente.
- No se crea una orden global"
- El estudio aparece como pagado.
- El recibo y la constancia quedan disponibles.