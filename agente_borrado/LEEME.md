# Agente de borrado (PCs que suben estudios)

Borra del disco de la PC los archivos (DICOM/JPG) que **el sistema confirma que ya
tiene guardados**. Funciona así:

1. Cuando el técnico sube imágenes, el sistema guarda la "huella" SHA-256 de cada
   archivo tal como llegó (`ImagenEstudio.huella_sha256`).
2. Cada pocos minutos, el agente calcula la huella de los archivos de la carpeta
   configurada (p. ej. la de RadiAnt) y le pregunta al sistema cuáles ya tiene
   (`POST /api/agente/huellas/`, con el token de la PC).
3. Solo esos se mandan a la Papelera (o se borran, según `modo`). Si el sistema no
   responde, o el archivo no se subió, o se subió distinto, **no se toca**.

Detalles de seguridad:

- El token de cada PC solo sirve para preguntar por huellas: no da acceso a
  pantallas ni a datos de pacientes. Se puede revocar en cualquier momento.
- No se confirma una imagen cuyo archivo ya no está en el servidor (p. ej. un JPG
  que la radióloga descartó), así nunca se borra la única copia.
- Los archivos modificados en los últimos `minutos_sin_cambios` minutos se
  ignoran (pueden estar copiándose todavía desde el equipo).
- Las imágenes subidas **antes** de instalar esto no tienen huella: esas no se
  borran. Hay que limpiarlas a mano.
- RadiAnt guarda su propio índice de estudios: después de borrar, los estudios
  pueden seguir apareciendo en su lista pero ya no se podrán abrir. Se pueden
  quitar de la lista desde RadiAnt.

## 1. Crear el token de la PC (en el servidor)

En la carpeta del sistema (`seminario subida`):

```
venv\Scripts\python manage.py token_agente crear "Rayos X sala 1"
```

Copiar el token que muestra (no se vuelve a mostrar). Otros comandos:
`token_agente listar`, `token_agente renovar "<nombre>"`, `token_agente revocar "<nombre>"`.
También se puede ver y revocar desde el admin de Django (Agentes de equipo).

## 2. Instalar en la PC

1. Copiar esta carpeta a la PC, p. ej. `C:\ClinicaAgente\`.
2. Copiar `agente.json.ejemplo` como `agente.json` y completar:
   - `token`: el del paso 1.
   - `carpetas`: la(s) carpeta(s) donde RadiAnt guarda los estudios (con `\\`
     dobles, como en el ejemplo). En RadiAnt se ve en las opciones del servidor
     DICOM/PACS, donde dice en qué carpeta guarda los archivos recibidos.
   - `modo`: `papelera` (recomendado) o `borrar` (borrado definitivo).
3. Probar sin borrar nada (muestra qué borraría):

   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File C:\ClinicaAgente\agente_borrado.ps1 -Simular
   ```

4. Programarlo cada 5 minutos, con el usuario que usa la PC:

   ```
   schtasks /Create /TN "ClinicaAgenteBorrado" /SC MINUTE /MO 5 /TR "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\ClinicaAgente\agente_borrado.ps1"
   ```

Lo que hace queda en `agente_borrado.log`, en la misma carpeta. Para quitarlo:
`schtasks /Delete /TN "ClinicaAgenteBorrado" /F`.
