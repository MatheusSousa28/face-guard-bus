from django.db import models
from usuarios.models import Instituicao, Motorista
from alunos.models import Aluno

class Veiculo(models.Model):
    modelo = models.CharField(max_length=100)
    capacidade = models.IntegerField()
    placa = models.CharField(max_length=10, unique=True)
    cor = models.CharField(max_length=30)
    foto = models.ImageField(upload_to='fotos_veiculos/', null=True, blank=True)
    
    instituicao = models.ForeignKey(Instituicao, on_delete=models.CASCADE)
    
    # Muitos-para-Muitos: Cria a tabela intermediária automaticamente
    alunos_autorizados = models.ManyToManyField(Aluno, related_name='veiculos', blank=True)
    motoristas_autorizados = models.ManyToManyField(Motorista, related_name='veiculos', blank=True)

    def __str__(self):
        return f"{self.modelo} ({self.placa})"

class Rota(models.Model):
    veiculo = models.ForeignKey(Veiculo, on_delete=models.SET_NULL, null=True, blank=True)
    motorista = models.ForeignKey(Motorista, on_delete=models.SET_NULL, null=True, blank=True)
    inicio = models.DateTimeField(null=True, blank=True)
    fim = models.DateTimeField(null=True, blank=True)
    ativa = models.BooleanField(default=False)

    def __str__(self):
        return f"Rota {self.id} - {self.veiculo.placa}"

class Localizacao(models.Model):
    rota = models.ForeignKey(Rota, on_delete=models.CASCADE, related_name='coordenadas')
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Localizações"