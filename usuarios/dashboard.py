from datetime import datetime, time, timedelta

from django.db.models import Count, F, OuterRef, Q, Subquery
from django.db.models.functions import TruncDate
from django.utils import timezone

from alunos.models import Aluno
from monitoramento.models import Evento
from transporte.models import Localizacao, Rota, Veiculo
from usuarios.models import Motorista, Responsavel


def contexto_dashboard_instituicao():
    """Métricas enxutas para a visão operacional institucional."""
    agora = timezone.now()
    limite_gps = agora - timedelta(seconds=90)
    ultima_localizacao = Localizacao.objects.filter(
        rota_id=OuterRef('pk'),
    ).order_by('-timestamp').values('timestamp')[:1]

    rotas_ativas_qs = Rota.objects.filter(
        ativa=True, interrompida=False,
    ).annotate(ultima_localizacao_dashboard=Subquery(ultima_localizacao))
    contagem_rotas = rotas_ativas_qs.aggregate(
        total=Count('pk'),
        gps_atualizado=Count('pk', filter=Q(ultima_localizacao_dashboard__gte=limite_gps)),
        sem_sinal=Count('pk', filter=(Q(ultima_localizacao_dashboard__lt=limite_gps)
                                      | Q(ultima_localizacao_dashboard__isnull=True))),
    )

    ultimo_evento_por_rota_aluno = Evento.objects.filter(
        rota_id=OuterRef('rota_id'), aluno_id=OuterRef('aluno_id'), autorizado=True,
    ).order_by('-data_hora', '-pk').values('pk')[:1]
    alunos_a_bordo = Evento.objects.filter(
        rota__ativa=True,
        aluno__isnull=False,
        aluno__deleted_at__isnull=True,
        autorizado=True,
    ).annotate(ultimo_evento=Subquery(ultimo_evento_por_rota_aluno)).filter(
        pk=F('ultimo_evento'), tipo='embarque',
    ).values('aluno_id').distinct().count()

    rotas_ativas = list(
        rotas_ativas_qs.select_related('veiculo', 'motorista__usuario')
        .order_by('-inicio')[:5]
    )
    for rota in rotas_ativas:
        rota.gps_atualizado_dashboard = bool(
            rota.ultima_localizacao_dashboard
            and rota.ultima_localizacao_dashboard >= limite_gps
        )

    return {
        'total_alunos': Aluno.objects.filter(deleted_at__isnull=True).count(),
        'alunos_pendentes': Aluno.objects.filter(
            deleted_at__isnull=True, is_aprovado=False,
        ).count(),
        'responsaveis_pendentes': Responsavel.objects.filter(
            deleted_at__isnull=True, usuario__is_aprovado=False,
        ).count(),
        'total_motoristas': Motorista.objects.filter(
            deleted_at__isnull=True, usuario__is_active=True, usuario__is_aprovado=True,
        ).count(),
        'total_veiculos': Veiculo.objects.count(),
        'rotas_ativas': contagem_rotas['total'],
        'rotas_com_gps': contagem_rotas['gps_atualizado'],
        'rotas_sem_sinal': contagem_rotas['sem_sinal'],
        'interrupcoes_pendentes': Rota.objects.filter(
            ativa=True, interrompida=True,
        ).count(),
        'alunos_a_bordo': alunos_a_bordo,
        'rotas_ativas_lista': rotas_ativas,
        'alertas_recentes': Evento.objects.filter(tipo='desconhecido')
        .select_related('rota__veiculo').order_by('-data_hora', '-pk')[:5],
    }


def contexto_dashboard_responsavel(responsavel):
    """Dados e eventos limitados aos alunos do responsável autenticado."""
    ultimo_evento = Evento.objects.filter(
        aluno_id=OuterRef('pk'), autorizado=True,
    ).exclude(tipo='desconhecido').order_by('-data_hora', '-pk')
    evento_em_rota_ativa = Evento.objects.filter(
        aluno_id=OuterRef('pk'), autorizado=True,
        rota__ativa=True, rota__interrompida=False,
    ).exclude(tipo='desconhecido').order_by('-data_hora', '-pk')

    alunos = list(
        Aluno.objects.filter(responsavel=responsavel, deleted_at__isnull=True)
        .annotate(
            ultimo_evento_tipo=Subquery(ultimo_evento.values('tipo')[:1]),
            ultimo_evento_data=Subquery(ultimo_evento.values('data_hora')[:1]),
            ultimo_evento_rota=Subquery(ultimo_evento.values('rota_id')[:1]),
            evento_ativo_tipo=Subquery(evento_em_rota_ativa.values('tipo')[:1]),
            evento_ativo_data=Subquery(evento_em_rota_ativa.values('data_hora')[:1]),
            evento_ativo_rota=Subquery(evento_em_rota_ativa.values('rota_id')[:1]),
        ).order_by('nome', 'pk')
    )
    alunos_aprovados_aviso = [
        aluno for aluno in alunos
        if aluno.is_aprovado and not aluno.responsavel_aprovacao_notificada
    ]
    ultimo_evento_por_aluno = Evento.objects.filter(
        aluno_id=OuterRef('aluno_id'), autorizado=True,
    ).exclude(tipo='desconhecido').order_by('-data_hora', '-pk').values('pk')[:1]
    eventos_rotas_interrompidas = Evento.objects.filter(
        aluno__in=alunos,
        autorizado=True,
        tipo='embarque',
        rota__ativa=True,
        rota__interrompida=True,
    ).annotate(ultimo_evento=Subquery(ultimo_evento_por_aluno)).filter(
        pk=F('ultimo_evento'),
    ).select_related('aluno', 'rota__veiculo').order_by('-data_hora', '-pk')
    avisos_rotas_por_id = {}
    for evento in eventos_rotas_interrompidas:
        aviso = avisos_rotas_por_id.setdefault(evento.rota_id, {
            'rota': evento.rota,
            'alunos': [],
        })
        aviso['alunos'].append(evento.aluno.nome)
    return {
        'alunos': alunos,
        'total_alunos': len(alunos),
        'alunos_pendentes': sum(not aluno.is_aprovado for aluno in alunos),
        'alunos_a_bordo': sum(aluno.evento_ativo_tipo == 'embarque' for aluno in alunos),
        'alunos_aprovados_aviso': alunos_aprovados_aviso,
        'avisos_rotas_interrompidas': list(avisos_rotas_por_id.values()),
    }


def tendencia_eventos_dashboard(dias=7):
    """Contagens por dia para o gráfico institucional carregado sob demanda."""
    hoje = timezone.localdate()
    inicio = hoje - timedelta(days=dias - 1)
    inicio_ts = timezone.make_aware(datetime.combine(inicio, time.min))
    fim_ts = timezone.make_aware(datetime.combine(hoje + timedelta(days=1), time.min))
    agregados = Evento.objects.filter(
        data_hora__gte=inicio_ts,
        data_hora__lt=fim_ts,
        tipo__in=('embarque', 'desembarque'),
        autorizado=True,
    ).annotate(
        dia=TruncDate('data_hora', tzinfo=timezone.get_current_timezone()),
    ).values('dia', 'tipo').annotate(
        total=Count('pk'),
    )
    por_dia = {(item['dia'], item['tipo']): item['total'] for item in agregados}
    return [
        {
            'dia': inicio + timedelta(days=offset),
            'embarques': por_dia.get((inicio + timedelta(days=offset), 'embarque'), 0),
            'desembarques': por_dia.get((inicio + timedelta(days=offset), 'desembarque'), 0),
        }
        for offset in range(dias)
    ]
