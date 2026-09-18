"""Filtro de template para chequear roles (Usuario.tiene_rol) desde HTML.

Django no permite pasarle argumentos a un método en un template
(`{{ user.tiene_rol('administrador') }}` no funciona), de ahí este filtro:
`{% load roles %}{% if user|tiene_rol:'administrador' %}...{% endif %}`.
"""
from django import template

register = template.Library()


@register.filter
def tiene_rol(usuario, rol):
    return bool(usuario and usuario.is_authenticated and usuario.tiene_rol(rol))
