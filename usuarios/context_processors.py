from alunos.models import Aluno
from transporte.models import Rota


def notificacoes_instituicao(request):
    usuario = request.user
    if not usuario.is_authenticated or not (
        usuario.is_superuser or hasattr(usuario, 'instituicao')
    ):
        return {
            'exibir_sino_instituicao': False,
            'notificacoes_instituicao_alunos': [],
            'notificacoes_instituicao_rotas': [],
            'notificacoes_instituicao_total': 0,
        }

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
    return {
        'exibir_sino_instituicao': True,
        'notificacoes_instituicao_alunos': alunos,
        'notificacoes_instituicao_rotas': rotas,
        'notificacoes_instituicao_total': len(alunos) + len(rotas),
    }
