from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def enable_rls(apps, schema_editor):
    # Supabase REST API 로 읽히지 않도록 (다른 테이블과 같은 규칙). 사이트는 RLS 를 우회하는 계정으로 접속.
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("alter table schedule_savedstaff enable row level security")
        schema_editor.execute("alter table schedule_rosterseed enable row level security")


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("schedule", "0016_schedule_manual"),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedStaff",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("keeper", "근무자"), ("anes", "마취의")], default="keeper", max_length=10)),
                ("name", models.CharField(max_length=50)),
                ("order", models.PositiveIntegerField(default=0)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="saved_staff",
                                           to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["order", "id"], "unique_together": {("user", "role", "name")}},
        ),
        migrations.CreateModel(
            name="RosterSeed",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("role", models.CharField(choices=[("keeper", "근무자"), ("anes", "마취의")], default="keeper", max_length=10)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="roster_seeds",
                                           to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("user", "date", "role")}},
        ),
        migrations.RunPython(enable_rls, migrations.RunPython.noop),
    ]
