from django.utils import timezone

from monitoramento.models import Evento
from transporte.models import Rota
from transporte.services import obter_estado_gps, processar_rotas_sem_gps


def obter_contexto_monitoramento():
    """Retorna os dados compartilhados do resumo institucional de frota."""
    processar_rotas_sem_gps()
    rotas_ativas = list(
        Rota.objects.filter(ativa=True, interrompida=False)
        .select_related('veiculo', 'motorista__usuario')
        .order_by('-inicio')
    )
    rotas_interrompidas_pendentes = list(
        Rota.objects.filter(interrompida=True, ativa=True)
        .select_related('veiculo', 'motorista__usuario', 'resolvida_por')
        .order_by('-interrompida_em')
    )
    rotas_interrompidas_encerradas = list(
        Rota.objects.filter(interrompida=True, ativa=False)
        .select_related('veiculo', 'motorista__usuario', 'resolvida_por')
        .order_by('-interrompida_em')[:10]
    )
    rotas_interrompidas = rotas_interrompidas_pendentes + rotas_interrompidas_encerradas
    rotas_operacionais = rotas_ativas + [rota for rota in rotas_interrompidas if rota.ativa]

    estado_alunos = {}
    eventos_ativos = Evento.objects.filter(
        rota__in=rotas_operacionais, aluno__isnull=False,
    ).select_related('aluno').order_by('data_hora', 'id')
    for evento in eventos_ativos:
        estado_alunos[(evento.rota_id, evento.aluno_id)] = evento.tipo

    agora = timezone.now()

    def montar_resumo_rota(rota):
        ultima_localizacao = rota.coordenadas.order_by('-timestamp').first()
        alunos_abordo = sum(
            1 for (rota_id, _), tipo in estado_alunos.items()
            if rota_id == rota.id and tipo == 'embarque'
        )
        estado_gps = obter_estado_gps(rota, ultima_localizacao, agora)
        return {
            'rota': rota,
            'ultima_localizacao': ultima_localizacao,
            'estado_gps': estado_gps,
            'gps_atualizado': estado_gps == 'atualizado',
            'alunos_abordo': alunos_abordo,
        }

    contexto_rotas = [montar_resumo_rota(rota) for rota in rotas_ativas]
    contexto_interrompidas = [montar_resumo_rota(rota) for rota in rotas_interrompidas]
    return {
        'rotas_ativas': contexto_rotas,
        'rotas_interrompidas': contexto_interrompidas,
        'total_rotas_ativas': sum(item['estado_gps'] == 'atualizado' for item in contexto_rotas),
        'total_rotas_sem_sinal': sum(item['estado_gps'] == 'sem_sinal' for item in contexto_rotas),
        'total_interrupcoes_pendentes': sum(item['rota'].ativa for item in contexto_interrompidas),
        'total_alunos_abordo': sum(
            item['alunos_abordo'] for item in contexto_rotas + contexto_interrompidas
            if item['rota'].ativa
        ),
        'alertas_recentes': Evento.objects.filter(tipo='desconhecido').select_related(
            'rota__veiculo'
        ).order_by('-data_hora')[:5],
    }
