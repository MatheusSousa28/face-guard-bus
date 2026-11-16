from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from transporte.models import ConfiguracaoFrota, Veiculo


class Command(BaseCommand):
    help = 'Substitui fotos da frota por imagens de referência e deixa um veículo sem foto.'

    @transaction.atomic
    def handle(self, *args, **options):
        configuracao, _ = ConfiguracaoFrota.objects.get_or_create(chave='fotos_referencia_aplicadas')
        configuracao = ConfiguracaoFrota.objects.select_for_update().get(pk=configuracao.pk)
        if configuracao.aplicado:
            self.stdout.write('As fotos de referência já foram aplicadas; nenhuma alteração necessária.')
            return

        veiculos = list(Veiculo.objects.order_by('pk'))
        if not veiculos:
            configuracao.aplicado = True
            configuracao.save(update_fields=['aplicado'])
            self.stdout.write(self.style.WARNING('Nenhum veículo cadastrado; inicialização marcada sem alterações.'))
            return

        arquivos = [
            settings.BASE_DIR / 'static/img/referencias/onibus-escolar-1.jpg',
            settings.BASE_DIR / 'static/img/referencias/onibus-escolar-2.jpg',
        ]
        if not all(path.is_file() for path in arquivos):
            self.stderr.write(self.style.ERROR('Arquivos de referência não encontrados em static/img/referencias/.'))
            return

        for indice, veiculo in enumerate(veiculos):
            foto_antiga = veiculo.foto
            if indice == 0:
                veiculo.foto = None
                veiculo.save(update_fields=['foto'])
                if foto_antiga:
                    foto_antiga.delete(save=True)
                self.stdout.write(f'{veiculo}: foto removida para demonstrar o ícone sem foto.')
                continue

            arquivo = arquivos[(indice - 1) % len(arquivos)]
            conteudo = arquivo.read_bytes()
            nome = f'referencia_onibus_{(indice - 1) % len(arquivos) + 1}.jpg'
            veiculo.foto.save(nome, ContentFile(conteudo), save=True)
            if foto_antiga and foto_antiga.name != veiculo.foto.name:
                foto_antiga.delete(save=False)
            self.stdout.write(f'{veiculo}: foto de referência aplicada.')

        self.stdout.write(self.style.SUCCESS(
            f'Fotos atualizadas em {len(veiculos)} veículo(s); o veículo de menor ID ficou sem foto.'
        ))
        configuracao.aplicado = True
        configuracao.save(update_fields=['aplicado'])
