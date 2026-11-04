from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from alunos.models import Aluno
from monitoramento.models import Evento
from transporte.models import Localizacao, Rota, Veiculo
from usuarios.models import Instituicao, Motorista, Responsavel, Usuario


DEMO_PASSWORD = 'DemoFaceGuard2026!'
DEMO_USERS = (
    ('instituicao', 'demo.escola@example.test', 'Escola', 'Demonstração'),
    ('motorista1', 'demo.motorista1@example.test', 'Marcos', 'Motorista Demo'),
    ('motorista2', 'demo.motorista2@example.test', 'Lucia', 'Motorista Demo'),
    ('responsavel1', 'demo.responsavel1@example.test', 'Ana', 'Responsável Demo'),
    ('responsavel2', 'demo.responsavel2@example.test', 'Paulo', 'Responsável Demo'),
)


class Command(BaseCommand):
    help = 'Cria dados fictícios e idempotentes para demonstrar mapas, frota e eventos.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--permitir-banco-compartilhado',
            action='store_true',
            help='Permite criar contas e rotas de demonstração quando SUPABASE_URL está configurada.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if getattr(settings, 'SUPABASE_URL', None) and not options['permitir_banco_compartilhado']:
            raise CommandError(
                'SUPABASE_URL está configurada. Por segurança, o comando não altera esse banco sem '
                'a opção explícita --permitir-banco-compartilhado.'
            )

        instituicao_usuario = self._usuario('demo.escola@example.test', 'Escola', 'Demonstração')
        Instituicao.objects.get_or_create(usuario=instituicao_usuario)

        motoristas = [
            self._motorista('demo.motorista1@example.test', 'Marcos', 'Motorista Demo', '90000000011'),
            self._motorista('demo.motorista2@example.test', 'Lucia', 'Motorista Demo', '90000000012'),
        ]
        responsaveis = [
            self._responsavel('demo.responsavel1@example.test', 'Ana', 'Responsável Demo', '90000000001'),
            self._responsavel('demo.responsavel2@example.test', 'Paulo', 'Responsável Demo', '90000000002'),
        ]
        alunos = [
            self._aluno('Davi Demonstração', 9, responsaveis[0]),
            self._aluno('Bia Demonstração', 11, responsaveis[0]),
            self._aluno('Caio Demonstração', 10, responsaveis[1]),
        ]
        veiculos = [
            self._veiculo('Van de demonstração', 'DEMO001', 'Branca', 12, motoristas[0], alunos[:2]),
            self._veiculo('Micro-ônibus de demonstração', 'DEMO002', 'Azul', 24, motoristas[1], alunos[2:]),
        ]

        agora = timezone.now()
        rotas_ativas = [
            self._rota_ativa(veiculos[0], motoristas[0], agora - timedelta(minutes=18)),
            self._rota_ativa(veiculos[1], motoristas[1], agora - timedelta(minutes=12)),
        ]
        caminhos_ativos = [
            [(-15.7801, -47.9295), (-15.7810, -47.9250), (-15.7825, -47.9220), (-15.7832, -47.9180)],
            [(-15.7650, -47.9100), (-15.7670, -47.9130), (-15.7690, -47.9160), (-15.7710, -47.9190)],
        ]
        for rota, caminho in zip(rotas_ativas, caminhos_ativos):
            self._sincronizar_localizacoes(
                rota,
                caminho,
                [agora - timedelta(seconds=45 - indice * 10) for indice in range(len(caminho))],
            )

        self._evento(rotas_ativas[0], alunos[0], 'embarque', agora - timedelta(minutes=8))
        self._evento(rotas_ativas[0], alunos[1], 'embarque', agora - timedelta(minutes=5))
        self._evento(rotas_ativas[1], alunos[2], 'embarque', agora - timedelta(minutes=6))

        inicio_historico = timezone.make_aware(datetime(2025, 1, 15, 11, 0, 0))
        rota_historica, _ = Rota.objects.get_or_create(
            veiculo=veiculos[0],
            motorista=motoristas[0],
            inicio=inicio_historico,
            defaults={'fim': inicio_historico + timedelta(minutes=22), 'ativa': False},
        )
        Rota.objects.filter(pk=rota_historica.pk).update(
            fim=inicio_historico + timedelta(minutes=22), ativa=False, interrompida=False,
        )
        caminho_historico = [
            (-15.7750, -47.9250), (-15.7770, -47.9220), (-15.7790, -47.9190),
            (-15.7820, -47.9160), (-15.7850, -47.9130),
        ]
        self._sincronizar_localizacoes(
            rota_historica,
            caminho_historico,
            [inicio_historico + timedelta(minutes=5 * indice) for indice in range(len(caminho_historico))],
        )
        self._evento(rota_historica, alunos[0], 'embarque', inicio_historico + timedelta(minutes=3))
        self._evento(rota_historica, alunos[0], 'desembarque', inicio_historico + timedelta(minutes=20))

        self.stdout.write(self.style.SUCCESS(
            'Dados de demonstração prontos: instituição, 2 motoristas, 2 responsáveis, 3 alunos, '
            '2 veículos, 2 rotas ativas com GPS e embarques, e 1 rota histórica com embarque/desembarque.'
        ))
        self.stdout.write(f'Login da instituição: demo.escola@example.test / {DEMO_PASSWORD}')
        self.stdout.write('As outras contas também usam essa senha; todos os registros são fictícios.')

    @staticmethod
    def _usuario(email, primeiro_nome, sobrenome):
        usuario, _ = Usuario.objects.get_or_create(
            email=email,
            defaults={
                'username': email,
                'first_name': primeiro_nome,
                'last_name': sobrenome,
                'is_aprovado': True,
            },
        )
        usuario.username = email
        usuario.first_name = primeiro_nome
        usuario.last_name = sobrenome
        usuario.is_aprovado = True
        usuario.is_active = True
        usuario.set_password(DEMO_PASSWORD)
        usuario.save(update_fields=[
            'username', 'first_name', 'last_name', 'is_aprovado', 'is_active', 'password',
        ])
        return usuario

    def _motorista(self, email, primeiro_nome, sobrenome, cpf):
        usuario = self._usuario(email, primeiro_nome, sobrenome)
        motorista, _ = Motorista.objects.update_or_create(
            usuario=usuario,
            defaults={'cpf': cpf, 'foto_perfil': ''},
        )
        return motorista

    def _responsavel(self, email, primeiro_nome, sobrenome, cpf):
        usuario = self._usuario(email, primeiro_nome, sobrenome)
        responsavel, _ = Responsavel.objects.update_or_create(
            usuario=usuario,
            defaults={'cpf': cpf, 'foto_perfil': ''},
        )
        return responsavel

    @staticmethod
    def _aluno(nome, idade, responsavel):
        aluno, _ = Aluno.objects.update_or_create(
            nome=nome,
            responsavel=responsavel,
            defaults={
                'idade': idade,
                'dados_faciais': '[]',
                'foto_perfil': '',
                'is_aprovado': True,
                'termo_consentimento': True,
            },
        )
        return aluno

    @staticmethod
    def _veiculo(modelo, placa, cor, capacidade, motorista, alunos):
        veiculo, _ = Veiculo.objects.update_or_create(
            placa=placa,
            defaults={'modelo': modelo, 'cor': cor, 'capacidade': capacidade},
        )
        veiculo.motoristas_autorizados.set([motorista])
        veiculo.alunos_autorizados.set(alunos)
        return veiculo

    @staticmethod
    def _rota_ativa(veiculo, motorista, inicio):
        rota = Rota.objects.filter(
            veiculo=veiculo, motorista=motorista, ativa=True, interrompida=False,
        ).first()
        if rota is None:
            rota = Rota.objects.create(
                veiculo=veiculo, motorista=motorista, inicio=inicio, ativa=True,
            )
        else:
            Rota.objects.filter(pk=rota.pk).update(inicio=inicio, fim=None)
            rota.inicio = inicio
            rota.fim = None
        return rota

    @staticmethod
    def _sincronizar_localizacoes(rota, caminho, horarios):
        existentes = list(rota.coordenadas.order_by('id'))
        if len(existentes) != len(caminho):
            if existentes:
                raise CommandError(
                    f'A rota de demonstração {rota.pk} já contém pontos GPS diferentes; '
                    'nenhum ponto foi removido automaticamente.'
                )
            existentes = [
                Localizacao.objects.create(rota=rota, latitude=lat, longitude=lng)
                for lat, lng in caminho
            ]
        for ponto, (latitude, longitude), horario in zip(existentes, caminho, horarios):
            Localizacao.objects.filter(pk=ponto.pk).update(
                latitude=latitude, longitude=longitude, timestamp=horario,
            )

    @staticmethod
    def _evento(rota, aluno, tipo, horario):
        evento, _ = Evento.objects.get_or_create(
            rota=rota,
            aluno=aluno,
            tipo=tipo,
            defaults={'autorizado': True},
        )
        Evento.objects.filter(pk=evento.pk).update(data_hora=horario, autorizado=True)
