from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transporte', '0007_rota_instituicao_ciente_encerramento'),
    ]

    operations = [
        migrations.AddField(
            model_name='rota',
            name='responsaveis_notificados_revisao',
            field=models.BooleanField(default=False),
        ),
    ]
