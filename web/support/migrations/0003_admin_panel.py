from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [("support", "0002_roles")]

    operations = [
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                Lower("email"), condition=~models.Q(email=""), name="unique_user_email_ci"
            ),
        ),
    ]
