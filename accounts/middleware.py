from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect

from . import trabajos


class SesionUnicaMiddleware:
    """Un mismo usuario no puede estar logueado en dos equipos a la vez.

    En cada login (ver accounts/apps.py -> _registrar_login_exitoso) se
    guarda la session_key en Usuario.sesion_activa. Acá se compara esa
    session_key contra la de la sesión que hizo el request actual: si no
    coincide, es que alguien inició sesión con este mismo usuario desde
    otro equipo después — se cierra esta sesión vieja y se manda al login
    con un aviso, en vez de dejar seguir navegando con datos de sesión que
    ya no son "la" sesión válida del usuario.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (
            user is not None
            and user.is_authenticated
            and user.sesion_activa
            and user.sesion_activa != request.session.session_key
        ):
            logout(request)
            messages.warning(
                request,
                'Tu sesión se cerró porque se inició sesión con este mismo '
                'usuario desde otro equipo.',
            )
            return redirect('login')

        return self.get_response(request)


PAGINA_RESTAURACION = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Restaurando el sistema - Clínica de Imágenes</title>
<style>
body{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#f0f4f8;color:#1e293b;margin:0;
display:flex;min-height:100vh;align-items:center;justify-content:center;padding:16px;box-sizing:border-box}
.caja{background:#fff;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,.08);
padding:28px;max-width:34rem;width:100%}
h1{font-size:1.25rem;margin:0 0 .4rem}p{margin:.3rem 0;color:#64748b;font-size:.92rem}
.barra{height:14px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin:1rem 0 .4rem}
.barra div{height:100%;width:0;background:#3b82f6;border-radius:999px;transition:width .4s ease}
strong{color:#1e293b}
</style></head><body><div class="caja">
<h1>Restaurando el sistema</h1>
<p id="etapa">Preparando…</p>
<div class="barra"><div id="relleno"></div></div>
<p><strong id="pct">0%</strong> &middot; No cierre esta página. Cuando termine, se abrirá sola.</p>
<p>Por seguridad, el sistema no atiende otras pantallas hasta que termine la restauración.</p>
</div>
<script>
(function(){
  function terminar(){ window.location.href = '/respaldos/'; }
  function consultar(){
    fetch('/respaldos/estado/', {credentials:'same-origin', headers:{'Accept':'application/json'}})
      .then(function(r){
        var t = r.headers.get('Content-Type') || '';
        if (t.indexOf('json') === -1) { throw new Error('fin'); }
        return r.json();
      })
      .then(function(d){
        if (d.estado !== 'corriendo') { terminar(); return; }
        document.getElementById('etapa').textContent = d.etapa || '';
        document.getElementById('relleno').style.width = d.porcentaje + '%';
        document.getElementById('pct').textContent = d.porcentaje + '%';
        setTimeout(consultar, 1000);
      })
      .catch(function(){ setTimeout(terminar, 1500); });
  }
  consultar();
})();
</script></body></html>"""


class ModoRestauracionMiddleware:
    """Mientras se restaura un respaldo la base de datos queda sin tablas unos
    instantes, así que ninguna pantalla puede tocarla. Va PRIMERO en la lista
    de middlewares: responde con una pantalla de mantenimiento con la barra de
    progreso (sin consultar la base) y solo deja pasar el avance del trabajo."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        estado = trabajos.estado()
        if estado and estado['tipo'] == 'restauracion' and estado['estado'] == 'corriendo':
            if request.path == '/respaldos/estado/':
                return JsonResponse(estado)
            respuesta = HttpResponse(PAGINA_RESTAURACION, status=503)
            respuesta['Retry-After'] = '30'
            respuesta['Cache-Control'] = 'no-store'
            return respuesta
        return self.get_response(request)
