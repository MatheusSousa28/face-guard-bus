from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid
import os

def renomear_foto_responsavel(instance, filename):
    extensao = filename.split('.')[-1]
    # Gera um nome como: 8f2a1b3c9d.jpg
    novo_nome = f"{uuid.uuid4().hex}.{extensao}"
    # Devolve o caminho completo: perfil_responsaveis/8f2a1b3c9d.jpg
    return os.path.join('perfil_responsaveis/', novo_nome)

def renomear_foto_motorista(instance, filename):
    extensao = filename.split('.')[-1]
    novo_nome = f"{uuid.uuid4().hex}.{extensao}"
    return os.path.join('perfil_motoristas/', novo_nome)

class Usuario(AbstractUser):
    email = models.EmailField(unique=True)
    #este campo existe pra que cadastros de responsáveis e alunos sejam aprovados pela instituição
    is_aprovado = models.BooleanField(default=False)

    #sobrescrevendo o campo de username padrão do django para email
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username'] 

    first_name = models.CharField("primeiro nome", max_length=150, blank=False)
    last_name = models.CharField("sobrenome", max_length=150, blank=False)

    def __str__(self):
        return self.email

class Instituicao(models.Model):
    #oneToOneField liga este perfil diretamente ao usuário base de login
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE)
    
    class Meta:
        verbose_name_plural = "Instituições"

    def __str__(self):
        return f"Instituição: {self.usuario.first_name}"

class Responsavel(models.Model):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE)
    cpf = models.CharField(max_length=11, unique=True)
    foto_perfil = models.ImageField(upload_to=renomear_foto_responsavel, null=False, blank=False)

    class Meta:
        verbose_name_plural = "Responsáveis"

    def __str__(self):
        return f"Responsável: {self.usuario.first_name}"

class Motorista(models.Model):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE)
    cpf = models.CharField(max_length=11, unique=True)
    foto_perfil = models.ImageField(upload_to=renomear_foto_motorista, null=False, blank=False)

    def __str__(self):
        return f"Motorista: {self.usuario.first_name}"