from django.test import TestCase
from django.urls import reverse

from alunos.models import Aluno
from usuarios.models import Responsavel, Usuario


class EdicaoAlunoResponsavelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user(
            username='familia@example.test', email='familia@example.test', password='SenhaForte123!',
            first_name='Ana', last_name='Responsável', is_aprovado=True,
        )
        cls.responsavel = Responsavel.objects.create(usuario=cls.usuario, cpf='90000000001')
        cls.aluno = Aluno.objects.create(
            nome='Davi', idade=9, responsavel=cls.responsavel,
            dados_faciais='[]', foto_perfil='', is_aprovado=True,
        )

    def test_edicao_de_aluno_sem_foto_exige_nova_foto(self):
        self.client.force_login(self.usuario)

        response = self.client.post(reverse('editar_aluno_responsavel', args=(self.aluno.pk,)), {
            'nome': 'Davi Atualizado', 'idade': '10',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A foto do aluno é obrigatória para identificação')
        self.aluno.refresh_from_db()
        self.assertEqual(self.aluno.nome, 'Davi')
        self.assertEqual(self.aluno.idade, 9)

    def test_responsavel_nao_edita_aluno_de_outra_familia(self):
        outro_usuario = Usuario.objects.create_user(
            username='outra@example.test', email='outra@example.test', password='SenhaForte123!',
            first_name='Bia', last_name='Responsável', is_aprovado=True,
        )
        Responsavel.objects.create(usuario=outro_usuario, cpf='90000000002')
        self.client.force_login(outro_usuario)

        response = self.client.get(reverse('editar_aluno_responsavel', args=(self.aluno.pk,)))

        self.assertEqual(response.status_code, 404)
