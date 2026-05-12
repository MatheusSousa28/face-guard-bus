from django.db import models
from usuarios.models import Responsavel

class Aluno(models.Model):
    nome = models.CharField(max_length=100)
    idade = models.IntegerField()
    #fk para o responsavel pelo aluno
    responsavel = models.ForeignKey(Responsavel, on_delete=models.CASCADE, related_name='alunos')
    #campo para armazenar dados faciais dos alunos
    dados_faciais = models.TextField(blank=True, null=True) 
    #campo para a foto visual que aparecerá no painel
    foto_perfil = models.ImageField(upload_to='perfil_alunos/', null=False, blank=False)
    #campo de aprovação de cadastro pela instituição
    is_aprovado = models.BooleanField(default=False)
    termo_consentimento = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.nome} (resp: {self.responsavel.usuario.first_name})"