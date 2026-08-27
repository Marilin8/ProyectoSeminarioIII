from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views
from .forms import LoginForm
from .models import Usuario

urlpatterns = [
    path('', LoginView.as_view(authentication_form=LoginForm), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('perfil/', views.mi_perfil, name='mi_perfil'),
    path('usuarios/nuevo/', views.crear_usuario, name='crear_usuario'),
    path(
        'usuarios/radiologos/',
        views.lista_usuarios,
        {'rol': Usuario.ROL_MEDICO_RADIOLOGO},
        name='lista_usuarios_radiologos',
    ),
    path(
        'usuarios/tecnicos/',
        views.lista_usuarios,
        {'rol': Usuario.ROL_TECNICO_IMAGENES},
        name='lista_usuarios_tecnicos',
    ),
    path(
        'usuarios/secretarias/',
        views.lista_usuarios,
        {'rol': Usuario.ROL_RECEPCIONISTA},
        name='lista_usuarios_secretarias',
    ),
    path('usuarios/<int:usuario_id>/editar/', views.editar_usuario, name='editar_usuario'),
    path('usuarios/<int:usuario_id>/estado/', views.cambiar_estado_usuario, name='cambiar_estado_usuario'),
    path('bitacora/', views.bitacora, name='bitacora'),
    path('pantalla/<slug:clave>/', views.pantalla_placeholder, name='pantalla_placeholder'),
]
