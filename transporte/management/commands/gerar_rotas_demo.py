from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from monitoramento.models import Evento
from transporte.models import Localizacao, Rota, Veiculo


class Command(BaseCommand):
    help = 'Cria rotas históricas fictícias para demonstrar o mapa do FaceGuard Bus.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--quantidade', type=int, default=2,
            help='Quantidade de rotas de demonstração a criar (padrão: 2).',
        )

    def handle(self, *args, **options):
        quantidade = options['quantidade']
        if quantidade < 1:
            raise CommandError('--quantidade precisa ser pelo menos 1.')

        veiculos = list(
            Veiculo.objects.filter(
                motoristas_autorizados__usuario__is_aprovado=True,
                alunos_autorizados__is_aprovado=True,
            ).distinct().prefetch_related('motoristas_autorizados', 'alunos_autorizados')
        )
        if not veiculos:
            raise CommandError(
                'Não há veículo com motorista e aluno aprovados associados. '
                'Cadastre/aprove os perfis e faça os vínculos pela gestão da frota antes de gerar os percursos.'
            )

        caminhos = [
            [
                (-15.7801, -47.9295), (-15.7810, -47.9250), (-15.7825, -47.9220),
                (-15.7830, -47.9210), (-15.7830, -47.9210), (-15.7830, -47.9210),
                (-15.7850, -47.9180), (-15.7870, -47.9150),
            ],
            [
                (-15.7650, -47.9100), (-15.7670, -47.9130), (-15.7690, -47.9160),
                (-15.7700, -47.9170), (-15.7700, -47.9170), (-15.7700, -47.9170),
                (-15.7730, -47.9200), (-15.7760, -47.9230),
            ],
        ]

        agora = timezone.now()
        criadas = []
        for indice in range(quantidade):
            veiculo = veiculos[indice % len(veiculos)]
            motoristas = [m for m in veiculo.motoristas_autorizados.all() if m.usuario.is_aprovado]
            alunos = [a for a in veiculo.alunos_autorizados.all() if a.is_aprovado]
            if not motoristas or not alunos:
                continue

            inicio = agora - timedelta(days=indice + 1, hours=1)
            rota = Rota.objects.create(
                veiculo=veiculo,
                motorista=motoristas[0],
                inicio=inicio,
                fim=inicio + timedelta(minutes=14),
                ativa=False,
            )
            caminho = caminhos[indice % len(caminhos)]
            for ponto_indice, (latitude, longitude) in enumerate(caminho):
                ponto = Localizacao.objects.create(
                    rota=rota, latitude=latitude, longitude=longitude,
                )
                # auto_now_add sobrescreve timestamp em save(); update mantém a data simulada.
                Localizacao.objects.filter(pk=ponto.pk).update(
                    timestamp=inicio + timedelta(minutes=2 * ponto_indice)
                )

            aluno = alunos[indice % len(alunos)]
            for tipo, minuto in (('embarque', 2), ('desembarque', 12)):
                evento = Evento.objects.create(
                    rota=rota, aluno=aluno, tipo=tipo, autorizado=True,
                )
                # O evento também usa auto_now_add; grava-se o horário da viagem fictícia.
                Evento.objects.filter(pk=evento.pk).update(
                    data_hora=inicio + timedelta(minutes=minuto)
                )
            criadas.append(rota.id)

        if not criadas:
            raise CommandError('Não foi possível criar rotas: os veículos não têm associações aprovadas válidas.')

        self.stdout.write(self.style.SUCCESS(
            f'Criadas {len(criadas)} rota(s) histórica(s) fictícia(s): {", ".join(map(str, criadas))}. '
            'Os registros podem ser removidos pelo painel administrativo.'
        ))
