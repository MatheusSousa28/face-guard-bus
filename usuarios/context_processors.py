from alunos.models import Aluno
from django.db.models import F, OuterRef, Subquery
from monitoramento.models import Evento
from transporte.models import Rota


def notificacoes_instituicao(request):
    usuario = request.user
    contexto = {
        'exibir_sino_instituicao': False,
        'exibir_sino_responsavel': False,
        'notificacoes_instituicao_alunos': [],
        'notificacoes_instituicao_rotas': [],
        'notificacoes_instituicao_total': 0,
        'notificacoes_responsavel_aprovacoes': [],
        'notificacoes_responsavel_rotas': [],
        'notificacoes_responsavel_rotas_revisadas': [],
        'notificacoes_responsavel_total': 0,
    }
    if not usuario.is_authenticated:
        return contexto

    if usuario.is_superuser or hasattr(usuario, 'instituicao'):
        alunos = list(
            Aluno.objects.filter(
                is_aprovado=False,
                instituicao_notificacao_vista=False,
                deleted_at__isnull=True,
            ).select_related('responsavel__usuario').order_by('pk')
        )
        rotas = list(
            Rota.objects.filter(ativa=True, interrompida=True)
            .select_related('veiculo', 'motorista__usuario')
            .order_by('-interrompida_em', '-pk')
        )
        contexto.update({
            'exibir_sino_instituicao': True,
            'notificacoes_instituicao_alunos': alunos,
            'notificacoes_instituicao_rotas': rotas,
            'notificacoes_instituicao_total': len(alunos) + len(rotas),
        })

    if hasattr(usuario, 'responsavel'):
        responsavel = usuario.responsavel
        aprovados = list(Aluno.objects.filter(
            responsavel=responsavel,
            is_aprovado=True,
            responsavel_aprovacao_notificada=False,
            deleted_at__isnull=True,
        ).order_by('nome', 'pk'))
        ultimo_evento = Evento.objects.filter(
            aluno_id=OuterRef('aluno_id'), autorizado=True,
        ).exclude(tipo='desconhecido').order_by('-data_hora', '-pk').values('pk')[:1]
        eventos_a_bordo = Evento.objects.filter(
            aluno__responsavel=responsavel,
            tipo='embarque',
            autorizado=True,
            rota__ativa=True,
            rota__interrompida=True,
        ).annotate(ultimo_evento=Subquery(ultimo_evento)).filter(
            pk=F('ultimo_evento'),
        ).values_list('rota_id', flat=True)
        eventos_revisados = Evento.objects.filter(
            aluno__responsavel=responsavel,
            tipo='embarque', autorizado=True,
            rota__ativa=False, rota__interrompida=True,
            rota__resolvida_por__isnull=False,
            rota__responsaveis_notificados_revisao=False,
        ).annotate(ultimo_evento=Subquery(ultimo_evento)).filter(
            pk=F('ultimo_evento'),
        ).values_list('rota_id', flat=True)
        rotas = list(
            Rota.objects.filter(pk__in=eventos_a_bordo)
            .select_related('veiculo', 'motorista__usuario')
            .order_by('-interrompida_em', '-pk')
        )
        rotas_revisadas = list(Rota.objects.filter(
            pk__in=eventos_revisados,
        ).select_related('veiculo', 'motorista__usuario', 'resolvida_por').distinct().order_by('-resolvida_em', '-pk'))
        for rota in rotas + rotas_revisadas:
            rota.alunos_do_responsavel = list(
                Evento.objects.filter(
                    rota=rota, aluno__responsavel=responsavel, tipo='embarque', autorizado=True,
                ).values_list('aluno__nome', flat=True).distinct()
            )
        contexto.update({
            'exibir_sino_responsavel': True,
            'notificacoes_responsavel_aprovacoes': aprovados,
            'notificacoes_responsavel_rotas': rotas,
            'notificacoes_responsavel_rotas_revisadas': rotas_revisadas,
            'notificacoes_responsavel_total': len(aprovados) + len(rotas) + len(rotas_revisadas),
        })
    return contexto
