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
