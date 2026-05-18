from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('board', '0007_alter_board_options_board_is_notice'),
    ]

    operations = [
        migrations.AddField(
            model_name='board',
            name='view_count',
            field=models.IntegerField(default=0),
        ),
    ]
