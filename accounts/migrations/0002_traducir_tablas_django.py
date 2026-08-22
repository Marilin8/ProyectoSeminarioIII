from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('admin', '0003_logentry_add_action_flag_choices'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('sessions', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql='RENAME TABLE auth_group TO grupos;',
            reverse_sql='RENAME TABLE grupos TO auth_group;',
        ),
        migrations.RunSQL(
            sql='RENAME TABLE auth_permission TO permisos;',
            reverse_sql='RENAME TABLE permisos TO auth_permission;',
        ),
        migrations.RunSQL(
            sql='RENAME TABLE auth_group_permissions TO grupos_permisos;',
            reverse_sql='RENAME TABLE grupos_permisos TO auth_group_permissions;',
        ),
        migrations.RunSQL(
            sql='RENAME TABLE django_content_type TO tipos_contenido;',
            reverse_sql='RENAME TABLE tipos_contenido TO django_content_type;',
        ),
        migrations.RunSQL(
            sql='RENAME TABLE django_session TO sesiones;',
            reverse_sql='RENAME TABLE sesiones TO django_session;',
        ),
        migrations.RunSQL(
            sql='RENAME TABLE django_admin_log TO registros_admin;',
            reverse_sql='RENAME TABLE registros_admin TO django_admin_log;',
        ),
    ]
