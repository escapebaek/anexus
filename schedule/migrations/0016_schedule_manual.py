from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("schedule", "0015_staff_off_duty"),
    ]

    operations = [
        migrations.AddField(
            model_name="surgeryschedule",
            name="manual",
            field=models.BooleanField(default=False),
        ),
    ]
