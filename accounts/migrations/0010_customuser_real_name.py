from django.db import migrations, models
from django.db.models import F


def populate_real_name(apps, schema_editor):
    CustomUser = apps.get_model('accounts', 'CustomUser')
    CustomUser.objects.filter(real_name='').update(real_name=F('username'))


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_alter_customuser_is_approved'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='real_name',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.RunPython(populate_real_name, migrations.RunPython.noop),
    ]
