from uuid import uuid4

from django.db import migrations, models
from django.db.models.functions import Lower


def seed_admin(apps, schema_editor):
    database = schema_editor.connection.alias
    users = apps.get_model("support", "User").objects.using(database)
    groups = apps.get_model("auth", "Group").objects.using(database)
    email = "test@test.test"
    if users.filter(email__iexact=email).exists():
        return
    user = users.create(
        email=email,
        username=uuid4().hex,
        password=(
            "pbkdf2_sha256$1200000$8e1fcc576598c457f3ac1d84c41aaf28$"
            "+Y9cPgKjDTesgmWLh+Eezrd9PDKfIRf4mUJ3Ozf4Mac="
        ),
    )
    user.groups.add(groups.get(name="Admin"))


class Migration(migrations.Migration):
    dependencies = [("support", "0002_roles")]

    operations = [
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                Lower("email"), condition=~models.Q(email=""), name="unique_user_email_ci"
            ),
        ),
        migrations.RunPython(seed_admin, migrations.RunPython.noop),
    ]
