from django.db import migrations, models
import usuarios.models


class Migration(migrations.Migration):
    dependencies = [('transporte', '0004_rota_interrompida_rota_interrompida_em_and_more')]

    operations = [
        migrations.AddField(
            model_name='veiculo',
            name='cor_avatar',
            field=models.CharField(choices=usuarios.models.CORES_AVATAR, default='#1d4ed8', max_length=7),
        ),
    ]
