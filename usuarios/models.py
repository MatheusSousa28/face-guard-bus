from django.db import models
from django.contrib.auth.models import AbstractUser

class Usuario(AbstractUser):
    email = models.EmailField(unique=True)
    #este campo existe pra que cadastros de responsáveis e alunos sejam aprovados pela instituição
    is_aprovado = models.BooleanField(default=False)

    #sobrescrevendo o campo de username padrão do django para email
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username'] 

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
    foto = models.ImageField(upload_to='fotos_responsaveis/', null=True, blank=True)

    class Meta:
        verbose_name_plural = "Responsáveis"

    def __str__(self):
        return f"Responsável: {self.usuario.first_name}"

class Motorista(models.Model):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE)
    cpf = models.CharField(max_length=11, unique=True)
    foto = models.ImageField(upload_to='fotos_motoristas/', null=True, blank=True)

    def __str__(self):
        return f"Motorista: {self.usuario.first_name}"