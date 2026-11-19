from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def enable_rls(apps, schema_editor):
    # Supabase REST API 로 읽히지 않도록 (다른 테이블과 같은 규칙). 사이트는 RLS 를 우회하는 계정으로 접속.
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("alter table schedule_roomrelief enable row level security")


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("schedule", "0018_schedule_deleted_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="RoomRelief",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("room", models.CharField(max_length=10)),
                ("slot", models.CharField(choices=[("am", "오전 커피"), ("lunch", "점심 식사"), ("pm", "오후 커피")], max_length=10)),
                ("name", models.CharField(max_length=50)),
                ("role", models.CharField(choices=[("keeper", "근무자"), ("anes", "마취의")], default="keeper", max_length=10)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="room_reliefs",
                                           to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("user", "date", "room", "slot")}},
        ),
        migrations.RunPython(enable_rls, migrations.RunPython.noop),
    ]
