from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path('', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('usuarios/nuevo/', views.crear_usuario, name='crear_usuario'),
    path('bitacora/', views.bitacora, name='bitacora'),
    path('pantalla/<slug:clave>/', views.pantalla_placeholder, name='pantalla_placeholder'),
]
