from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("schedule", "0014_staff_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="dutystaff",
            name="off",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="dutystaff",
            name="duty",
            field=models.CharField(
                blank=True,
                choices=[("", "-"), ("today", "오늘 당직"), ("yesterday", "어제 당직")],
                default="",
                max_length=10,
            ),
        ),
    ]
