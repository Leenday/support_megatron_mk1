"""The three roles as auth groups; their permissions come with the views (#16, #17, #18)."""

from django.db import migrations

ROLES = ("Requester", "Specialist", "Admin")  # a copy: migrations must not import models


def create_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ROLES:
        Group.objects.get_or_create(name=name)


def delete_roles(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=ROLES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("support", "0001_initial"),
    ]

    operations = [migrations.RunPython(create_roles, delete_roles)]
