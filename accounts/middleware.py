from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect


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
