# Reporte de Auditoría de Seguridad - Clínica de Imágenes (2/10/2026, teniendo en cuenta hasta Sprint 10)

**Proyecto:** Sistema de Gestión Médica  
**Entorno de Evaluación:** Desarrollo / Pruebas Dinámicas y Estáticas  
**Herramientas Utilizadas:** Django Security Check (SAST), Caido Proxy (DAST), OpenCode  
**Fecha:** Octubre 2026  

---

## 1. Resumen Ejecutivo

Se realizó una auditoría de seguridad integral dividida en dos enfoques:
1. **Análisis Estático (SAST):** Verificación del código fuente y configuraciones de Django mediante `python manage.py check --deploy`.
2. **Análisis Dinámico (DAST):** Fuzzing de endpoints, inspección de tráfico HTTP y validación de controles de acceso utilizando **Caido**.

---

## 2. Hallazgos de Configuración del Framework (SAST - Django Check)

Mediante la herramienta de diagnóstico de despliegue de Django, se identificaron **6 advertencias de seguridad** clave en `settings.py`:

| Código | Regla de Seguridad | Estado | Impacto / Riesgo |
| :--- | :--- | :--- | :--- |
| **W018** | `DEBUG` Mode | ⚠️ Activo (`True`) | **Alto:** Exposicion de trazas de código, URLs internas y variables de entorno ante errores 404/500. |
| **W009** | `SECRET_KEY` Insegura | ⚠️ Vulnerable | **Alto:** Llave por defecto o corta; compromete la firma de sesiones y tokens CSRF. |
| **W012** | `SESSION_COOKIE_SECURE` | ⚠️ Deshabilitado | **Medio:** Las cookies de sesión pueden transmitirse por HTTP no cifrado (riesgo de interception). |
| **W016** | `CSRF_COOKIE_SECURE` | ⚠️ Deshabilitado | **Medio:** Las cookies de protección contra CSRF no exigen HTTPS. |
| **W008** | `SECURE_SSL_REDIRECT` | ⚠️ Deshabilitado | **Medio:** No se fuerza la redirección automática de peticiones HTTP a HTTPS. |
| **W004** | `SECURE_HSTS_SECONDS` | ⚠️ Ausente | **Bajo:** Falta la cabecera HSTS para obligar el uso exclusivo de conexiones cifradas. |

---

## 3. Pruebas Dinámicas y Control de Acceso (DAST - Caido)

Utilizando **Caido Proxy**, se capturó el tráfico en tiempo real y se ejecutaron pruebas en el módulo **Automate**:

* **Prueba de Escalación de Privilegios / Fuzzing de Rutas:**
  * **Procedimiento:** Con un identificador de sesión activo con rol de **Recepcionista**, se automatizó el envío de peticiones hacia rutas restringidas (`/planilla/`, `/bitacora/`, `/admin/`, `/usuarios/radiologos/`, `/comisiones/historial/`).
  * **Resultado:** **Aprobado (Conforme).** El servidor respondió en todas las solicitudes con un código de estado **`302 Found`**, confirmando que el backend de Django valida correctamente la autorización y redirige las peticiones no autorizadas.

* **Resiliencia y Rate Limiting:**
  * **Hallazgo:** Ausencia de middleware de limitación de tasa (*Rate Limiting*). El servidor procesa múltiples peticiones consecutivas en endpoints de autenticación sin aplicar bloqueos temporales (`429 Too Many Requests`).

---

## 4. Plan de Remediación Recomendado

1. **Gestión de Entorno de Producción:**
   * Configurar un archivo `.env` independiente fuera del control de versiones.
   * Establecer `DEBUG = False` y generar una `SECRET_KEY` aleatoria de al menos 50 caracteres.
2. **Endurecimiento de Cookies y HTTPS:**
   * Activar `SESSION_COOKIE_SECURE = True` y `CSRF_COOKIE_SECURE = True`.
   * Habilitar `SECURE_SSL_REDIRECT = True` y configurar la cabecera HSTS.
3. **Control de Tasa (Rate Limiting):**
   * Integrar `django-ratelimit` en las vistas de autenticación para mitigar intentos de fuerza bruta.