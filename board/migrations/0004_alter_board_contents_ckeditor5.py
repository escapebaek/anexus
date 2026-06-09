import django_ckeditor_5.fields
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("board", "0003_alter_board_contents"),
    ]

    operations = [
        migrations.AlterField(
            model_name="board",
            name="contents",
            field=django_ckeditor_5.fields.CKEditor5Field(
                config_name="default", default="default"
            ),
        ),
    ]
