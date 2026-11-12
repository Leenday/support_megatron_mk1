from django.db import migrations


def create_requester_role(apps, schema_editor):
    groups = apps.get_model("auth", "Group").objects.using(schema_editor.connection.alias)
    groups.get_or_create(name="Requester")


class Migration(migrations.Migration):
    dependencies = [("support", "0007_merge_admin_panel_and_systems")]

    operations = [migrations.RunPython(create_requester_role, migrations.RunPython.noop)]
