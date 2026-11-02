from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from monitoramento.models import Evento
from .models import Localizacao, Rota


GPS_SEM_SINAL_APOS = timedelta(seconds=90)
ROTA_INTERROMPIDA_APOS = timedelta(minutes=15)


def contar_alunos_a_bordo(rota):
    status_por_aluno = {}
    eventos = Evento.objects.filter(
        rota=rota, aluno__isnull=False,
    ).order_by('data_hora', 'id').values_list('aluno_id', 'tipo')
    for aluno_id, tipo in eventos:
        status_por_aluno[aluno_id] = tipo
    return sum(tipo == 'embarque' for tipo in status_por_aluno.values())


def processar_rotas_sem_gps(agora=None, motorista_id=None, veiculo_id=None):
    """Marca rotas sem GPS há 15 minutos como interrompidas, sob lock."""
    agora = agora or timezone.now()
    rotas = Rota.objects.filter(ativa=True, interrompida=False).order_by('pk')
    if motorista_id is not None:
        rotas = rotas.filter(motorista_id=motorista_id)
    if veiculo_id is not None:
        rotas = rotas.filter(veiculo_id=veiculo_id)

    atualizadas = []
    with transaction.atomic():
        for rota in rotas.select_for_update():
            ultima_localizacao = Localizacao.objects.filter(rota=rota).order_by('-timestamp').first()
            ultima_atividade = ultima_localizacao.timestamp if ultima_localizacao else rota.inicio
            if ultima_atividade and agora - ultima_atividade < ROTA_INTERROMPIDA_APOS:
                continue

            rota.interrompida = True
            rota.interrompida_em = agora
            campos = ['interrompida', 'interrompida_em']
            if contar_alunos_a_bordo(rota) == 0:
                rota.ativa = False
                rota.fim = agora
                campos.extend(['ativa', 'fim'])
            rota.save(update_fields=campos)
            atualizadas.append(rota.pk)

    return atualizadas


def obter_estado_gps(rota, ultima_localizacao=None, agora=None):
    if rota.interrompida:
        return 'interrompida'
    if ultima_localizacao is None:
        ultima_localizacao = Localizacao.objects.filter(rota=rota).order_by('-timestamp').first()
    agora = agora or timezone.now()
    if ultima_localizacao and agora - ultima_localizacao.timestamp <= GPS_SEM_SINAL_APOS:
        return 'atualizado'
    return 'sem_sinal'
