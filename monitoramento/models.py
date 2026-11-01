from django.db import models
from alunos.models import Aluno
from transporte.models import Rota

class Evento(models.Model):
    TIPO_EVENTO_CHOICES = (
        ('embarque', 'Embarque'),
        ('desembarque', 'Desembarque'),
        ('desconhecido', 'Face Desconhecida'), #caso a imagem facial do aluno não seja reconhecida
    )
    data_hora = models.DateTimeField(auto_now_add=True)
    
    #rota na qual o evento ocorreu
    rota = models.ForeignKey(Rota, on_delete=models.CASCADE, related_name='eventos')
    
    #aluno reconhecido. Se o tipo for 'desconhecido', este campo pode ficar nulo.
    aluno = models.ForeignKey(Aluno, on_delete=models.CASCADE, null=True, blank=True, related_name='eventos')
    
    tipo = models.CharField(max_length=20, choices=TIPO_EVENTO_CHOICES)
    
    #para salvar a foto que a câmera tirou no momento
    foto_capturada = models.ImageField(upload_to='capturas_camera/', null=True, blank=True)
    
    #flag para saber se o embarque foi autorizado
    autorizado = models.BooleanField(default=False)

    def __str__(self):
        nome_aluno = self.aluno.nome if self.aluno else "Desconhecido"
        return f"{self.get_tipo_display()} - {nome_aluno} em {self.data_hora.strftime('%d/%m/%Y %H:%M')}"

    class Meta:
        verbose_name_plural = "Eventos"
        ordering = ['-data_hora'] #ordena do mais recente para o mais antigo