from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        # Las tablas internas de Django (auth, contenttypes, sessions, admin) se
        # renombran a español vía una migración con RunSQL (ver
        # accounts/migrations/0002_traducir_tablas_django.py). Django sigue
        # buscando esos modelos con sus nombres de tabla originales en inglés
        # salvo que se lo indiquemos aquí, así que apuntamos cada modelo a su
        # nueva tabla para que el ORM funcione en tiempo de ejecución.
        from django.contrib.admin.models import LogEntry
        from django.contrib.auth.models import Group, Permission
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.sessions.models import Session

        Group._meta.db_table = 'grupos'
        Permission._meta.db_table = 'permisos'
        Group.permissions.through._meta.db_table = 'grupos_permisos'
        ContentType._meta.db_table = 'tipos_contenido'
        Session._meta.db_table = 'sesiones'
        LogEntry._meta.db_table = 'registros_admin'

        # `manage.py migrate` intenta, al final, auto-crear los ContentType y
        # Permission faltantes usando el estado "congelado" de las migraciones
        # (que sigue teniendo los nombres de tabla en inglés, porque un RunSQL
        # no actualiza ese estado). Como las tablas reales ya no se llaman así,
        # esa auto-creación revienta en cada `migrate`. La desactivamos: como
        # este proyecto solo usa superusuarios (que no dependen de permisos
        # finos), no hace falta. Si más adelante se necesitan permisos por
        # rol, hay que crearlos a mano con las clases reales ya parcheadas.
        from django.contrib.auth.management import create_permissions
        from django.contrib.contenttypes.management import create_contenttypes
        from django.db.models.signals import post_migrate

        post_migrate.disconnect(
            create_permissions,
            dispatch_uid='django.contrib.auth.management.create_permissions',
        )
        post_migrate.disconnect(create_contenttypes)

        # Bitácora: registra cada inicio de sesión (exitoso o fallido) sin
        # tener que reemplazar la LoginView genérica que ya se usa en
        # accounts/urls.py.
        from django.contrib.auth.signals import user_logged_in, user_login_failed

        from .models import Bitacora, Usuario

        def _registrar_login_exitoso(sender, request, user, **kwargs):
            # request.session.session_key puede venir en None acá: si en esa
            # misma sesión ya había otro usuario logueado, login() la vació
            # (flush()) un momento antes y todavía no se generó una key
            # nueva (eso pasa recién al guardar la sesión). Forzamos que
            # exista antes de guardarla, si no sesion_activa quedaría NULL
            # y el UPDATE revienta (la columna no admite NULL).
            if not request.session.session_key:
                request.session.save()

            # Sesión única: este login pasa a ser la sesión "válida" del
            # usuario. SesionUnicaMiddleware va a cerrar cualquier otra
            # sesión abierta en otro equipo en cuanto esa haga su próxima
            # petición.
            user.sesion_activa = request.session.session_key
            user.save(update_fields=['sesion_activa'])

            Bitacora.registrar(
                request=request,
                usuario=user,
                username_intento=user.username,
                accion=Bitacora.ACCION_LOGIN_EXITOSO,
                descripcion=f'Inicio de sesión de "{user.username}".',
            )

        def _registrar_login_fallido(sender, credentials, request=None, **kwargs):
            username = credentials.get('username', '') or ''
            usuario = Usuario.objects.filter(username=username).first()
            Bitacora.registrar(
                request=request,
                usuario=usuario,
                username_intento=username,
                accion=Bitacora.ACCION_LOGIN_FALLIDO,
                descripcion=f'Intento de inicio de sesión fallido para "{username}".',
            )

        # weak=False: por default Django conecta con una referencia debil, y
        # como estas funciones son locales a ready() (no quedan con un
        # nombre a nivel de modulo), nada mas las referencia una vez que
        # ready() termina -- Python las recicla (garbage collection) y la
        # señal queda conectada a una función que ya no existe, sin avisar
        # el error. Por eso el login dejó de aparecer en la bitácora.
        user_logged_in.connect(
            _registrar_login_exitoso, dispatch_uid='bitacora_login_exitoso', weak=False,
        )
        user_login_failed.connect(
            _registrar_login_fallido, dispatch_uid='bitacora_login_fallido', weak=False,
        )
