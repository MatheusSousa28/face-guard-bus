from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('transporte', '0005_veiculo_cor_avatar')]

    operations = [
        migrations.CreateModel(
            name='ConfiguracaoFrota',
            fields=[
                ('chave', models.CharField(max_length=80, primary_key=True, serialize=False)),
                ('aplicado', models.BooleanField(default=False)),
            ],
        ),
    ]
