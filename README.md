# ProyectoSeminarioIII

## Base de datos local (Docker)

Este repo incluye una copia de la base de datos (`db_init/01_clinica_imagenes_main.sql`)
que se carga automáticamente en un contenedor MySQL la primera vez que lo levantas.

### Primer uso, después de clonar

1. Copia `.env.example` a `.env` y ajusta valores si hace falta:

   ```bash
   cp .env.example .env
   ```

2. Levanta la base de datos:

   ```bash
   docker-compose up -d
   ```

   La primera vez, MySQL tarda unos segundos en arrancar y cargar el dump
   (`db_init/01_clinica_imagenes_main.sql`) dentro del contenedor. Puedes
   revisar el progreso con:

   ```bash
   docker-compose logs -f db
   ```

3. Instala dependencias de Python y levanta el proyecto Django como siempre:

   ```bash
   pip install -r requirements.txt
   python manage.py runserver
   ```

   No hace falta correr `migrate`: el dump ya trae el esquema y los datos.

### Notas

- Los datos quedan en un volumen Docker (`db_data`) que persiste aunque hagas
  `docker-compose down`. Si quieres reiniciar la base desde cero (y que se
  vuelva a cargar el dump), usa:

  ```bash
  docker-compose down -v
  docker-compose up -d
  ```

- `.env` está en `.gitignore` y no se sube al repo; cada quien mantiene el suyo
  a partir de `.env.example`.

## HU-50 y HU-52 corregidas

El flujo actualizado de estudios y pagos separa la boleta bancaria original de
los documentos internos de la clínica:

```text
Recepción
  ↓
Crear cita
  ↓
Marcar llegada
  ↓
Generar orden
  ↓
Caja registra el pago
  ├─ Selecciona forma de pago
  ├─ Escribe número de boleta/referencia
  └─ Adjunta boleta bancaria si corresponde
  ↓
Se genera el recibo interno
  ↓
Se genera la constancia interna
  ↓
Se imprime y firma la constancia
  ↓
Se sube la constancia firmada
  ↓
Técnico consulta los documentos
  ↓
Radiólogo consulta los documentos
  ↓
Radiólogo adjunta el informe
  ↓
Recepción envía el estudio
```

### Cómo probarlo de forma sencilla

1. Ingrese con un usuario de Recepción, cree una cita y marque la llegada del
   paciente.
2. Genere la orden de trabajo y abra la pantalla de Caja.
3. Seleccione la forma de pago, escriba la referencia y adjunte la boleta
   bancaria cuando corresponda. Para transferencias, el archivo es obligatorio.
4. Abra el **recibo interno** y genere la **constancia interna**.
5. Descargue o imprima la constancia, fírmela y súbala desde Caja.
6. Ingrese como Técnico o Radiólogo para consultar el recibo, la boleta
   bancaria y la constancia firmada.
7. El Técnico carga las imágenes; el Radiólogo adjunta el informe.
8. Recepción envía el estudio al paciente. El envío permanece bloqueado si el
   pago todavía está pendiente.

Los documentos de un cobro pagado se consultan desde las pantallas de Caja,
Recepción, Técnico y Radiólogo. Los cobros pendientes no permiten visualizar
documentos de pago.

(Portado 2026-09-12 desde el commit "HU-50, HU-52 Corregido" de la rama
`visual-andres`.)
