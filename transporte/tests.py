import json
import base64
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from alunos.models import Aluno
from monitoramento.models import Evento
from transporte.models import Localizacao, Rota, Veiculo
from usuarios.models import Instituicao, Motorista, Responsavel


Usuario = get_user_model()


class TransporteFluxosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instituicao_usuario = Usuario.objects.create_user(
            username='escola@example.test',
            email='escola@example.test',
            password='SenhaForte123',
            first_name='Escola',
            last_name='Teste',
            is_aprovado=True,
        )
        cls.instituicao = Instituicao.objects.create(usuario=cls.instituicao_usuario)

        cls.motorista_usuario = Usuario.objects.create_user(
            username='motorista@example.test',
            email='motorista@example.test',
            password='SenhaForte123',
            first_name='Motorista',
            last_name='Teste',
            is_aprovado=True,
        )
        cls.motorista = Motorista.objects.create(usuario=cls.motorista_usuario, cpf='12345678901')

        cls.responsavel_usuario = Usuario.objects.create_user(
            username='responsavel@example.test',
            email='responsavel@example.test',
            password='SenhaForte123',
            first_name='Responsável',
            last_name='Teste',
            is_aprovado=True,
        )
        cls.responsavel = Responsavel.objects.create(
            usuario=cls.responsavel_usuario,
            cpf='10987654321',
            foto_perfil='perfil_responsaveis/teste.jpg',
        )
        cls.aluno = Aluno.objects.create(
            nome='Aluno Teste',
            idade=10,
            responsavel=cls.responsavel,
            dados_faciais='[]',
            foto_perfil='perfil_alunos/teste.jpg',
            is_aprovado=True,
            termo_consentimento=True,
        )
        cls.veiculo = Veiculo.objects.create(
            modelo='Van de teste', capacidade=12, placa='ABC1234', cor='Branca'
        )
        cls.veiculo.motoristas_autorizados.add(cls.motorista)
        cls.veiculo.alunos_autorizados.add(cls.aluno)

    def criar_rota(self):
        return Rota.objects.create(
            veiculo=self.veiculo,
            motorista=self.motorista,
            inicio=timezone.now(),
            ativa=True,
        )

    def test_motorista_nao_pode_finalizar_com_aluno_a_bordo(self):
        rota = self.criar_rota()
        Evento.objects.create(rota=rota, aluno=self.aluno, tipo='embarque', autorizado=True)
        self.client.force_login(self.motorista_usuario)

        response = self.client.post(reverse('finalizar_rota'))

        rota.refresh_from_db()
        self.assertRedirects(response, reverse('home'))
        self.assertTrue(rota.ativa)

    def test_motorista_inicia_rota_com_veiculo_autorizado(self):
        self.client.force_login(self.motorista_usuario)

        response = self.client.post(reverse('iniciar_rota'), {'veiculo_id': self.veiculo.id})

        self.assertRedirects(response, reverse('home'))
        rota = Rota.objects.get(motorista=self.motorista, ativa=True)
        self.assertEqual(rota.veiculo, self.veiculo)
        self.assertIsNotNone(rota.inicio)

    def test_motorista_nao_pode_iniciar_veiculo_nao_autorizado(self):
        outro_veiculo = Veiculo.objects.create(
            modelo='Van não autorizada', capacidade=8, placa='ZZZ1111', cor='Prata',
        )
        self.client.force_login(self.motorista_usuario)

        response = self.client.post(reverse('iniciar_rota'), {'veiculo_id': outro_veiculo.id})

        self.assertRedirects(response, reverse('home'))
        self.assertFalse(Rota.objects.filter(motorista=self.motorista, ativa=True).exists())

    def test_inicio_e_fim_de_rota_rejeitam_get(self):
        self.client.force_login(self.motorista_usuario)

        inicio = self.client.get(reverse('iniciar_rota'))
        fim = self.client.get(reverse('finalizar_rota'))

        self.assertEqual(inicio.status_code, 405)
        self.assertEqual(fim.status_code, 405)

    def test_motorista_pode_finalizar_quando_todos_desembarcaram(self):
        rota = self.criar_rota()
        Evento.objects.create(rota=rota, aluno=self.aluno, tipo='embarque', autorizado=True)
        Evento.objects.create(rota=rota, aluno=self.aluno, tipo='desembarque', autorizado=True)
        self.client.force_login(self.motorista_usuario)

        response = self.client.post(reverse('finalizar_rota'))

        rota.refresh_from_db()
        self.assertRedirects(response, reverse('home'))
        self.assertFalse(rota.ativa)
        self.assertIsNotNone(rota.fim)

    def test_painel_de_rota_ativa_exibe_camera_embutida(self):
        self.criar_rota()
        self.client.force_login(self.motorista_usuario)

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ativar câmera')
        self.assertContains(response, 'Capturar embarque/desembarque')
        self.assertContains(response, 'setInterval(enviarLocalizacao, 3000)')
        self.assertContains(response, 'maximumAge: 0')

    def test_tela_de_monitoramento_resume_gps_e_alunos_a_bordo(self):
        rota = self.criar_rota()
        Evento.objects.create(rota=rota, aluno=self.aluno, tipo='embarque', autorizado=True)
        Localizacao.objects.create(rota=rota, latitude=-15.78, longitude=-47.92)
        self.client.force_login(self.instituicao_usuario)

        response = self.client.get(reverse('mapa_unificado'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Alunos a bordo')
        self.assertContains(response, 'GPS atualizado')
        self.assertEqual(response.context['total_alunos_abordo'], 1)

    def test_home_da_instituicao_mantem_acesso_ao_monitoramento_sem_resumo(self):
        self.client.force_login(self.instituicao_usuario)

        response = self.client.get(reverse('home'))
        html = response.content.decode()

        self.assertLess(html.index('Acesso Administrativo (Instituição)'), html.index('href="/transporte/mapa-unificado/"'))
        self.assertContains(response, 'Monitoramento')
        self.assertNotContains(response, 'Resumo do monitoramento')
        self.assertNotContains(response, 'Rotas com GPS atualizado')

    @override_settings(CARTO_API_KEY='cartotestkey')
    def test_tela_de_mapa_mostra_resumo_institucional_abaixo_do_mapa(self):
        self.client.force_login(self.instituicao_usuario)

        response = self.client.get(reverse('mapa_unificado'))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertLess(html.index('id="mapa-frota"'), html.index('Resumo do monitoramento'))
        self.assertContains(response, 'Acompanhamento da frota')
        self.assertContains(response, 'id="painel-acompanhamento"')
        self.assertContains(response, 'Mostrar mapa e informações')
        self.assertContains(response, "const cartoApiKey = 'cartotestkey';")
        self.assertContains(response, 'basemaps.cartocdn.com')
        self.assertNotContains(response, 'tile.openstreetmap.org')

    def test_interrupcoes_sao_exibidas_em_carrossel_navegavel(self):
        primeira = self.criar_rota()
        primeira.interrompida = True
        primeira.interrompida_em = timezone.now()
        primeira.save(update_fields=['interrompida', 'interrompida_em'])
        segundo_veiculo = Veiculo.objects.create(
            modelo='Ônibus de teste', capacidade=30, placa='DEF5678', cor='Azul',
        )
        Rota.objects.create(
            veiculo=segundo_veiculo, motorista=self.motorista, inicio=timezone.now(),
            ativa=False, interrompida=True, interrompida_em=timezone.now(),
        )
        self.client.force_login(self.instituicao_usuario)

        response = self.client.get(reverse('mapa_unificado'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-roledescription="carrossel"')
        self.assertContains(response, 'id="interrupcao-anterior"')
        self.assertContains(response, 'id="proxima-interrupcao"')
        self.assertEqual(response.content.decode().count('class="interrupcao-slide'), 2)

    def test_mapa_sem_rota_selecionada_mostra_todos_os_onibus_ativos(self):
        rota_1 = self.criar_rota()
        Localizacao.objects.create(rota=rota_1, latitude=-15.78, longitude=-47.92)
        veiculo_2 = Veiculo.objects.create(
            modelo='Micro-ônibus teste', capacidade=20, placa='XYZ9876', cor='Azul',
        )
        rota_2 = Rota.objects.create(
            veiculo=veiculo_2, motorista=self.motorista, inicio=timezone.now(), ativa=True,
        )
        Localizacao.objects.create(rota=rota_2, latitude=-15.77, longitude=-47.91)
        self.client.force_login(self.instituicao_usuario)

        response = self.client.get(reverse('api_mapa_unificado'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload['rota'])
        self.assertEqual(payload['trajeto'], [])
        self.assertEqual({p['rota_id'] for p in payload['posicoes_ativas']}, {rota_1.id, rota_2.id})
        self.assertEqual(len(payload['rotas']), 2)

    def test_mapa_pode_selecionar_rota_historica_e_exibir_seu_trajeto(self):
        rota = self.criar_rota()
        rota.ativa = False
        rota.fim = timezone.now()
        rota.save(update_fields=['ativa', 'fim'])
        Localizacao.objects.create(rota=rota, latitude=-15.78, longitude=-47.92)
        self.client.force_login(self.instituicao_usuario)

        response = self.client.get(reverse('api_mapa_unificado'), {'rota': rota.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['rota']['id'], rota.id)
        self.assertEqual(len(payload['trajeto']), 1)

    def test_comando_de_dados_demo_cria_fluxo_completo_e_e_idempotente(self):
        with override_settings(SUPABASE_URL=''):
            call_command('popular_dados_demo', stdout=StringIO())
            call_command('popular_dados_demo', stdout=StringIO())

        self.assertTrue(Instituicao.objects.filter(usuario__email='demo.escola@example.test').exists())
        self.assertEqual(Veiculo.objects.filter(placa__startswith='DEMO').count(), 2)
        self.assertEqual(Rota.objects.filter(veiculo__placa__startswith='DEMO', ativa=True).count(), 2)
        self.assertEqual(Rota.objects.filter(veiculo__placa__startswith='DEMO', ativa=False).count(), 1)
        self.assertTrue(Evento.objects.filter(rota__veiculo__placa__startswith='DEMO', tipo='embarque').exists())
        self.assertTrue(Evento.objects.filter(rota__veiculo__placa__startswith='DEMO', tipo='desembarque').exists())

    @override_settings(SUPABASE_URL='postgresql://demo.invalid/example')
    def test_comando_de_dados_demo_bloqueia_banco_supabase_sem_confirmacao(self):
        with self.assertRaises(CommandError):
            call_command('popular_dados_demo', stdout=StringIO())

        self.assertFalse(Usuario.objects.filter(email='demo.escola@example.test').exists())

    def test_rota_sem_gps_por_mais_de_15_minutos_e_encerrada_sem_alunos_a_bordo(self):
        rota = self.criar_rota()
        Rota.objects.filter(pk=rota.pk).update(inicio=timezone.now() - timedelta(minutes=16))
        self.client.force_login(self.instituicao_usuario)

        response = self.client.get(reverse('mapa_unificado'))

        rota.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(rota.ativa)
        self.assertTrue(rota.interrompida)
        self.assertIsNotNone(rota.fim)
        self.assertContains(response, 'Encerrada automaticamente por falta de GPS')

    def test_rota_sem_gps_com_aluno_a_bordo_fica_pendente_e_reserva_recursos(self):
        rota = self.criar_rota()
        Rota.objects.filter(pk=rota.pk).update(inicio=timezone.now() - timedelta(minutes=16))
        Evento.objects.create(rota=rota, aluno=self.aluno, tipo='embarque', autorizado=True)
        self.client.force_login(self.instituicao_usuario)

        response = self.client.get(reverse('mapa_unificado'))

        rota.refresh_from_db()
        self.assertTrue(rota.ativa)
        self.assertTrue(rota.interrompida)
        self.assertContains(response, 'Revisão necessária')
        self.assertContains(response, 'permanecem reservados')

    def test_rota_com_gps_sem_sinal_por_mais_de_90_segundos_ainda_pode_retornar(self):
        rota = self.criar_rota()
        ponto = Localizacao.objects.create(rota=rota, latitude=-15.78, longitude=-47.92)
        Localizacao.objects.filter(pk=ponto.pk).update(timestamp=timezone.now() - timedelta(minutes=2))
        self.client.force_login(self.instituicao_usuario)

        response = self.client.get(reverse('mapa_unificado'))

        rota.refresh_from_db()
        self.assertTrue(rota.ativa)
        self.assertFalse(rota.interrompida)
        self.assertContains(response, 'Sem sinal')
        self.assertEqual(response.context['total_rotas_sem_sinal'], 1)

    def test_iniciar_rota_libera_rota_fantasma_sem_alunos_a_bordo(self):
        rota_antiga = self.criar_rota()
        Rota.objects.filter(pk=rota_antiga.pk).update(inicio=timezone.now() - timedelta(minutes=16))
        self.client.force_login(self.motorista_usuario)

        response = self.client.post(reverse('iniciar_rota'), {'veiculo_id': self.veiculo.id})

        rota_antiga.refresh_from_db()
        self.assertRedirects(response, reverse('home'))
        self.assertFalse(rota_antiga.ativa)
        self.assertTrue(rota_antiga.interrompida)
        self.assertEqual(Rota.objects.filter(motorista=self.motorista, ativa=True).count(), 1)

    def test_instituicao_pode_resolver_interrupcao_com_registro_de_revisao(self):
        rota = self.criar_rota()
        Rota.objects.filter(pk=rota.pk).update(inicio=timezone.now() - timedelta(minutes=16))
        Evento.objects.create(rota=rota, aluno=self.aluno, tipo='embarque', autorizado=True)
        self.client.force_login(self.instituicao_usuario)
        self.client.get(reverse('mapa_unificado'))

        response = self.client.post(reverse('resolver_rota_interrompida', args=(rota.pk,)), {
            'observacao': 'Aluno localizado e situação confirmada pela instituição.',
            'confirmacao_seguranca': 'on',
        })

        rota.refresh_from_db()
        self.assertRedirects(response, reverse('home'))
        self.assertFalse(rota.ativa)
        self.assertEqual(rota.resolvida_por, self.instituicao_usuario)
        self.assertIsNotNone(rota.resolvida_em)
        self.assertEqual(rota.observacao_resolucao, 'Aluno localizado e situação confirmada pela instituição.')

    def test_gps_nao_reativa_rota_interrompida_aguardando_revisao(self):
        rota = self.criar_rota()
        Rota.objects.filter(pk=rota.pk).update(inicio=timezone.now() - timedelta(minutes=16))
        Evento.objects.create(rota=rota, aluno=self.aluno, tipo='embarque', autorizado=True)
        self.client.force_login(self.motorista_usuario)

        response = self.client.post(
            reverse('api_gps'),
            data=json.dumps({'latitude': -15.78, 'longitude': -47.92}),
            content_type='application/json',
        )

        rota.refresh_from_db()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['status'], 'interrompida')
        self.assertTrue(rota.ativa)
        self.assertTrue(rota.interrompida)
        self.assertFalse(Localizacao.objects.filter(rota=rota).exists())

    def test_instituicao_pode_acessar_cadastro_de_motorista(self):
        self.client.force_login(self.instituicao_usuario)

        response = self.client.get(reverse('cadastrar_motorista'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cadastrar motorista')

    def test_responsavel_nao_pode_acessar_cadastro_de_motorista(self):
        self.client.force_login(self.responsavel_usuario)

        response = self.client.get(reverse('cadastrar_motorista'))

        self.assertRedirects(response, reverse('home'))

    def test_instituicao_associa_alunos_em_lote_ao_veiculo(self):
        segundo_aluno = Aluno.objects.create(
            nome='Segundo Aluno', idade=8, responsavel=self.responsavel,
            dados_faciais='[]', foto_perfil='perfil_alunos/segundo.jpg', is_aprovado=True,
        )
        self.client.force_login(self.instituicao_usuario)

        response = self.client.post(reverse('novo_veiculo'), {
            'modelo': 'Micro-ônibus', 'capacidade': '20', 'placa': 'XYZ9876', 'cor': 'Azul',
            'motoristas': [str(self.motorista.id)],
            'alunos': [str(self.aluno.id), str(segundo_aluno.id)],
        })

        novo_veiculo = Veiculo.objects.get(placa='XYZ9876')
        self.assertRedirects(response, reverse('painel_veiculos'))
        self.assertSetEqual(
            set(novo_veiculo.alunos_autorizados.values_list('id', flat=True)),
            {self.aluno.id, segundo_aluno.id},
        )

    def test_veiculo_nao_associa_alunos_ou_motoristas_nao_aprovados(self):
        motorista_pendente_usuario = Usuario.objects.create_user(
            username='pendente-motorista@example.test', email='pendente-motorista@example.test',
            password='SenhaForte123', first_name='Pendente', last_name='Motorista',
        )
        motorista_pendente = Motorista.objects.create(
            usuario=motorista_pendente_usuario, cpf='12345678902',
        )
        aluno_pendente = Aluno.objects.create(
            nome='Aluno Pendente', idade=9, responsavel=self.responsavel,
            dados_faciais='[]', foto_perfil='perfil_alunos/pendente.jpg', is_aprovado=False,
        )
        self.client.force_login(self.instituicao_usuario)

        self.client.post(reverse('novo_veiculo'), {
            'modelo': 'Van', 'capacidade': '10', 'placa': 'DEF5678', 'cor': 'Branca',
            'motoristas': [str(motorista_pendente.id)], 'alunos': [str(aluno_pendente.id)],
        })

        veiculo = Veiculo.objects.get(placa='DEF5678')
        self.assertFalse(veiculo.motoristas_autorizados.exists())
        self.assertFalse(veiculo.alunos_autorizados.exists())

    def test_veiculo_rejeita_placa_duplicada_sem_alterar_o_existente(self):
        self.client.force_login(self.instituicao_usuario)

        response = self.client.post(reverse('novo_veiculo'), {
            'modelo': 'Outro modelo', 'capacidade': '10', 'placa': self.veiculo.placa.lower(),
            'cor': 'Preta', 'motoristas': [], 'alunos': [],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Veiculo.objects.filter(placa=self.veiculo.placa).count(), 1)
        self.assertEqual(Veiculo.objects.get(pk=self.veiculo.pk).modelo, 'Van de teste')

    def test_nao_pode_excluir_veiculo_com_historico_de_rota(self):
        self.criar_rota()
        self.client.force_login(self.instituicao_usuario)

        response = self.client.post(reverse('deletar_veiculo', args=(self.veiculo.id,)))

        self.assertRedirects(response, reverse('painel_veiculos'))
        self.assertTrue(Veiculo.objects.filter(pk=self.veiculo.pk).exists())

    def test_gps_rejeita_coordenada_fora_do_intervalo(self):
        self.criar_rota()
        self.client.force_login(self.motorista_usuario)

        response = self.client.post(
            reverse('api_gps'),
            data=json.dumps({'latitude': 120, 'longitude': -70}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Localizacao.objects.count(), 0)

    def test_gps_rejeita_nan_e_json_malformado(self):
        self.criar_rota()
        self.client.force_login(self.motorista_usuario)

        nan_response = self.client.post(
            reverse('api_gps'), data='{"latitude":"NaN","longitude":-70}', content_type='application/json',
        )
        malformed_response = self.client.post(
            reverse('api_gps'), data='{', content_type='application/json',
        )

        self.assertEqual(nan_response.status_code, 400)
        self.assertEqual(malformed_response.status_code, 400)
        self.assertEqual(Localizacao.objects.count(), 0)

    def test_reconhecimento_registra_embarque_e_depois_desembarque(self):
        rota = self.criar_rota()
        self.aluno.dados_faciais = json.dumps([0.1] * 128)
        self.aluno.save(update_fields=['dados_faciais'])
        self.client.force_login(self.motorista_usuario)
        captura = 'data:image/jpeg;base64,' + base64.b64encode(b'captura-teste').decode('ascii')

        with patch('transporte.views.face_recognition.load_image_file'), \
             patch('transporte.views.face_recognition.face_encodings', return_value=[object()]), \
             patch('transporte.views.face_recognition.compare_faces', return_value=[True]):
            embarque = self.client.post(
                reverse('api_reconhecimento'), data=json.dumps({'imagem': captura}),
                content_type='application/json',
            )
            Evento.objects.filter(rota=rota, aluno=self.aluno).update(
                data_hora=timezone.now() - timedelta(seconds=15),
            )
            desembarque = self.client.post(
                reverse('api_reconhecimento'), data=json.dumps({'imagem': captura}),
                content_type='application/json',
            )

        self.assertEqual(embarque.json()['tipo'], 'embarque')
        self.assertEqual(desembarque.json()['tipo'], 'desembarque')
        self.assertEqual(
            list(Evento.objects.filter(rota=rota, aluno=self.aluno).values_list('tipo', flat=True)),
            ['desembarque', 'embarque'],
        )

    def test_reconhecimento_de_face_desconhecida_cria_alerta_sem_salvar_imagem(self):
        rota = self.criar_rota()
        self.client.force_login(self.motorista_usuario)
        captura = 'data:image/jpeg;base64,' + base64.b64encode(b'captura-teste').decode('ascii')

        with patch('transporte.views.face_recognition.load_image_file'), \
             patch('transporte.views.face_recognition.face_encodings', return_value=[object()]):
            response = self.client.post(
                reverse('api_reconhecimento'), data=json.dumps({'imagem': captura}),
                content_type='application/json',
            )

        evento = Evento.objects.get(rota=rota, tipo='desconhecido')
        self.assertEqual(response.json()['status'], 'desconhecido')
        self.assertFalse(evento.foto_capturada)

    def test_reconhecimento_rejeita_captura_com_multiplos_rostos(self):
        rota = self.criar_rota()
        self.client.force_login(self.motorista_usuario)
        captura = 'data:image/jpeg;base64,' + base64.b64encode(b'captura-teste').decode('ascii')

        with patch('transporte.views.face_recognition.load_image_file'), \
             patch('transporte.views.face_recognition.face_encodings', return_value=[object(), object()]):
            response = self.client.post(
                reverse('api_reconhecimento'), data=json.dumps({'imagem': captura}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['status'], 'multiplos_rostos')
        self.assertFalse(Evento.objects.filter(rota=rota).exists())

    def test_historico_do_responsavel_retorna_apenas_rotas_com_seu_aluno(self):
        rota = self.criar_rota()
        Localizacao.objects.create(rota=rota, latitude=-23.550520, longitude=-46.633308)
        Evento.objects.create(rota=rota, aluno=self.aluno, tipo='embarque', autorizado=True)
        self.client.force_login(self.responsavel_usuario)

        response = self.client.get(reverse('api_mapa_unificado'), {'rota': rota.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['rota']['id'], rota.id)
        self.assertEqual(len(payload['eventos']), 1)
        self.assertEqual(payload['eventos'][0]['aluno'], self.aluno.nome)

    def test_instituicao_ve_alerta_desconhecido_e_parada_estimada(self):
        rota = self.criar_rota()
        inicio = timezone.now() - timedelta(minutes=6)
        Rota.objects.filter(pk=rota.pk).update(inicio=inicio)
        for minuto in (0, 2, 4):
            ponto = Localizacao.objects.create(
                rota=rota, latitude=-15.78, longitude=-47.92,
            )
            Localizacao.objects.filter(pk=ponto.pk).update(
                timestamp=inicio + timedelta(minutes=minuto)
            )
        Evento.objects.create(rota=rota, tipo='desconhecido', autorizado=False)
        self.client.force_login(self.instituicao_usuario)

        response = self.client.get(reverse('api_mapa_unificado'), {'rota': rota.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload['alertas']), 1)
        self.assertEqual(len(payload['paradas']), 1)
        self.assertEqual(payload['paradas'][0]['duracao_minutos'], 4)

    def test_responsavel_nao_recebe_eventos_de_outro_responsavel(self):
        rota = self.criar_rota()
        outro_usuario = Usuario.objects.create_user(
            username='outro@example.test', email='outro@example.test', password='SenhaForte123',
            first_name='Outro', last_name='Responsável', is_aprovado=True,
        )
        outro_responsavel = Responsavel.objects.create(
            usuario=outro_usuario, cpf='11223344556', foto_perfil='perfil_responsaveis/outro.jpg'
        )
        outro_aluno = Aluno.objects.create(
            nome='Aluno de outra família', idade=9, responsavel=outro_responsavel,
            dados_faciais='[]', foto_perfil='perfil_alunos/outro.jpg', is_aprovado=True,
        )
        Evento.objects.create(rota=rota, aluno=outro_aluno, tipo='embarque', autorizado=True)
        self.client.force_login(self.responsavel_usuario)

        response = self.client.get(reverse('api_mapa_unificado'))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['rota'])
