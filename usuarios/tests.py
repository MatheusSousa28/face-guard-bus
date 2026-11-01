import io
import base64
import json
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from alunos.models import Aluno
from usuarios.models import Instituicao, Motorista, Responsavel


Usuario = get_user_model()


class FluxosCadastroTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_temporaria = tempfile.TemporaryDirectory()
        cls.config_media = override_settings(MEDIA_ROOT=cls.media_temporaria.name)
        cls.config_media.enable()

    @classmethod
    def tearDownClass(cls):
        cls.config_media.disable()
        cls.media_temporaria.cleanup()
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        cls.instituicao_usuario = Usuario.objects.create_user(
            username='instituicao@test.local', email='instituicao@test.local',
            password='SenhaForte123!', first_name='Escola', last_name='Teste', is_aprovado=True,
        )
        cls.instituicao = Instituicao.objects.create(usuario=cls.instituicao_usuario)
        cls.responsavel_usuario = Usuario.objects.create_user(
            username='responsavel@test.local', email='responsavel@test.local',
            password='SenhaForte123!', first_name='Responsável', last_name='Teste', is_aprovado=True,
        )
        cls.responsavel = Responsavel.objects.create(
            usuario=cls.responsavel_usuario, cpf='12345678901', foto_perfil='fotos/responsavel.png',
        )

    def imagem_png(self, nome='foto.png'):
        buffer = io.BytesIO()
        Image.new('RGB', (32, 32), color='blue').save(buffer, format='PNG')
        return SimpleUploadedFile(nome, buffer.getvalue(), content_type='image/png')

    def test_responsavel_cadastrado_fica_pendente_e_senha_tem_hash(self):
        response = self.client.post(reverse('cadastro'), {
            'first_name': 'Ana', 'last_name': 'Silva', 'email': ' ANA@example.test ',
            'cpf': '123.456.789-02', 'senha': 'SenhaForte123!',
            'confirmar_senha': 'SenhaForte123!', 'foto_perfil': self.imagem_png(),
        })

        self.assertRedirects(response, reverse('login'))
        usuario = Usuario.objects.get(email='ana@example.test')
        self.assertFalse(usuario.is_aprovado)
        self.assertTrue(usuario.check_password('SenhaForte123!'))
        self.assertTrue(Responsavel.objects.filter(usuario=usuario).exists())

    def test_responsavel_nao_pode_cadastrar_sem_foto_valida(self):
        response = self.client.post(reverse('cadastro'), {
            'first_name': 'Ana', 'last_name': 'Silva', 'email': 'ana@example.test',
            'cpf': '12345678902', 'senha': 'SenhaForte123!',
            'confirmar_senha': 'SenhaForte123!',
        })

        self.assertRedirects(response, reverse('cadastro'))
        self.assertFalse(Usuario.objects.filter(email='ana@example.test').exists())

    def test_instituicao_cadastra_motorista_aprovado_com_senha_hash(self):
        self.client.force_login(self.instituicao_usuario)

        response = self.client.post(reverse('cadastrar_motorista'), {
            'first_name': 'João', 'last_name': 'Motorista', 'email': 'joao@example.test',
            'cpf': '12345678903', 'senha': 'SenhaForte123!',
            'foto_perfil': self.imagem_png('motorista.png'),
        })

        self.assertRedirects(response, reverse('painel_usuarios'))
        motorista = Motorista.objects.get(usuario__email='joao@example.test')
        self.assertTrue(motorista.usuario.is_aprovado)
        self.assertTrue(motorista.usuario.check_password('SenhaForte123!'))

    def test_responsavel_nao_pode_criar_motorista(self):
        self.client.force_login(self.responsavel_usuario)

        response = self.client.post(reverse('cadastrar_motorista'), {
            'first_name': 'João', 'last_name': 'Motorista', 'email': 'joao@example.test',
            'cpf': '12345678903', 'senha': 'SenhaForte123!',
            'foto_perfil': self.imagem_png('motorista.png'),
        })

        self.assertRedirects(response, reverse('home'))
        self.assertFalse(Motorista.objects.filter(usuario__email='joao@example.test').exists())

    def test_logout_encerra_sessao_para_permitir_troca_de_perfil(self):
        self.client.force_login(self.responsavel_usuario)

        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('login'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertRedirects(self.client.get(reverse('home')), reverse('login') + '?next=/home/')

    def test_aprovacao_de_cadastro_exige_post(self):
        pendente = Usuario.objects.create_user(
            username='pendente@test.local', email='pendente@test.local',
            password='SenhaForte123!', first_name='Pendente', last_name='Teste',
        )
        responsavel_pendente = Responsavel.objects.create(
            usuario=pendente, cpf='12345678904', foto_perfil='fotos/pendente.png',
        )
        self.client.force_login(self.instituicao_usuario)

        response_get = self.client.get(reverse('aprovar_cadastro', args=('responsavel', responsavel_pendente.id)))
        self.assertEqual(response_get.status_code, 405)
        self.assertFalse(Usuario.objects.get(pk=pendente.pk).is_aprovado)

        response_post = self.client.post(reverse('aprovar_cadastro', args=('responsavel', responsavel_pendente.id)))
        self.assertRedirects(response_post, reverse('painel_aprovacoes'))
        self.assertTrue(Usuario.objects.get(pk=pendente.pk).is_aprovado)

    def test_cadastro_de_aluno_exige_consentimento(self):
        self.client.force_login(self.responsavel_usuario)

        response = self.client.post(reverse('cadastro_aluno'), {
            'nome': 'Criança Teste', 'idade': '8', 'foto_base64': 'data:image/jpeg;base64,ZmFrZQ==',
        })

        self.assertRedirects(response, reverse('cadastro_aluno'))
        self.assertFalse(Aluno.objects.filter(nome='Criança Teste').exists())

    def test_cadastro_de_aluno_rejeita_idade_invalida_sem_tentar_processar_face(self):
        self.client.force_login(self.responsavel_usuario)

        response = self.client.post(reverse('cadastro_aluno'), {
            'nome': 'Criança Teste', 'idade': 'idade-inválida',
            'foto_base64': 'data:image/jpeg;base64,ZmFrZQ==', 'termo': 'on',
        })

        self.assertRedirects(response, reverse('cadastro_aluno'))
        self.assertFalse(Aluno.objects.filter(nome='Criança Teste').exists())

    def test_responsavel_nao_pode_aprovar_cadastros(self):
        pendente = Usuario.objects.create_user(
            username='aguardando@test.local', email='aguardando@test.local',
            password='SenhaForte123!', first_name='Aguardando', last_name='Teste',
        )
        perfil = Responsavel.objects.create(
            usuario=pendente, cpf='12345678905', foto_perfil='fotos/aguardando.png',
        )
        self.client.force_login(self.responsavel_usuario)

        response = self.client.post(reverse('aprovar_cadastro', args=('responsavel', perfil.id)))

        self.assertRedirects(response, reverse('home'))
        self.assertFalse(Usuario.objects.get(pk=pendente.pk).is_aprovado)

    @patch('alunos.views.face_recognition.face_encodings')
    @patch('alunos.views.face_recognition.load_image_file')
    def test_cadastro_de_aluno_registra_consentimento_e_aguarda_aprovacao(self, load_image, encodings):
        class Encoding:
            def tolist(self):
                return [0.1] * 128

        encodings.return_value = [Encoding()]
        self.client.force_login(self.responsavel_usuario)
        imagem = io.BytesIO()
        Image.new('RGB', (32, 32), color='green').save(imagem, format='JPEG')
        captura = 'data:image/jpeg;base64,' + base64.b64encode(imagem.getvalue()).decode('ascii')

        response = self.client.post(reverse('cadastro_aluno'), {
            'nome': 'Criança Teste', 'idade': '8', 'foto_base64': captura, 'termo': 'on',
        })

        self.assertRedirects(response, reverse('home'))
        aluno = Aluno.objects.get(nome='Criança Teste')
        self.assertTrue(aluno.termo_consentimento)
        self.assertFalse(aluno.is_aprovado)
        self.assertEqual(len(json.loads(aluno.dados_faciais)), 128)
        load_image.assert_called_once()
