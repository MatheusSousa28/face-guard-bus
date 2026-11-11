from django.contrib.auth import get_user_model

from .models import RegistroAuditoria


class AuditoriaMiddleware:
    """Registra ações que alteram dados sem armazenar conteúdo sensível do formulário."""

    METODOS_AUDITAVEIS = {'POST', 'PUT', 'PATCH', 'DELETE'}
    ROTAS_EXCLUIDAS = {'/transporte/api/gps/'}
    ACOES = {
        'login': 'Entrou no sistema',
        'logout': 'Saiu do sistema',
        'aprovar_cadastro': 'Aprovou um cadastro',
        'reprovar_cadastro': 'Reprovou um cadastro',
        'api_redefinir_senha_usuario': 'Redefiniu a senha de uma conta',
        'iniciar_rota': 'Iniciou uma rota',
        'finalizar_rota': 'Finalizou uma rota',
        'resolver_rota_interrompida': 'Revisou uma rota interrompida',
        'api_reconhecimento': 'Registrou um evento de transporte',
        'gerenciar_veiculo': 'Cadastrou ou atualizou um veículo',
        'deletar_veiculo': 'Excluiu um veículo',
        'alterar_senha_propria': 'Alterou a própria senha',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario_antes = getattr(request, 'user', None)
        id_antes = getattr(usuario_antes, 'pk', None) if getattr(usuario_antes, 'is_authenticated', False) else None
        email_antes = getattr(usuario_antes, 'email', '') if id_antes else ''

        response = self.get_response(request)

        if request.method not in self.METODOS_AUDITAVEIS or request.path_info in self.ROTAS_EXCLUIDAS:
            return response

        usuario_depois = getattr(request, 'user', None)
        id_depois = getattr(usuario_depois, 'pk', None) if getattr(usuario_depois, 'is_authenticated', False) else None
        email_depois = getattr(usuario_depois, 'email', '') if id_depois else ''
        usuario_id = id_depois or id_antes
        usuario_email = email_depois or email_antes
        if not usuario_id:
            return response

        usuario = get_user_model().objects.filter(pk=usuario_id).first()
        match = getattr(request, 'resolver_match', None)
        nome_view = match.url_name if match else ''
        acao = self.ACOES.get(nome_view)
        if nome_view in {'api_usuarios', 'api_usuario_detalhe'}:
            if request.method == 'DELETE':
                acao = 'Excluiu um perfil de usuário'
            elif request.method == 'POST':
                acao = 'Criou um perfil de usuário' if getattr(match, 'kwargs', {}).get('obj_id') is None else 'Atualizou um perfil de usuário'
        if not acao:
            acao = {
                'POST': 'Enviou uma ação',
                'PUT': 'Atualizou dados',
                'PATCH': 'Atualizou dados',
                'DELETE': 'Excluiu um registro',
            }[request.method]

        RegistroAuditoria.objects.create(
            usuario=usuario,
            usuario_email=usuario_email,
            acao=acao,
            caminho=request.path_info[:255],
            metodo=request.method,
            status_code=response.status_code,
            ip=request.META.get('REMOTE_ADDR') or None,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:512],
        )
        return response
