from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseNotAllowed, JsonResponse
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Usuario, Responsavel, Motorista
from .monitoramento import obter_contexto_monitoramento
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
import re
import base64
import json
import io
import secrets
from django.core.paginator import Paginator, EmptyPage
from django.core.files.base import ContentFile
from alunos.models import Aluno
from transporte.models import Rota
from transporte.services import processar_rotas_sem_gps
from monitoramento.models import Evento
from PIL import Image, UnidentifiedImageError


def _senha_valida(senha):
    return bool(re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z\d]).{8,}$', senha or ''))


def _imagem_valida(arquivo, limite_bytes=5 * 1024 * 1024):
    if not arquivo or arquivo.size > limite_bytes:
        return False
    try:
        arquivo.seek(0)
        imagem = Image.open(arquivo)
        imagem.verify()
        arquivo.seek(0)
        return imagem.format in {'JPEG', 'PNG', 'WEBP'}
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        arquivo.seek(0)
        return False


def _imagem_perfil_edicao_valida(arquivo, limite_bytes=2 * 1024 * 1024):
    """Valida fotos de perfil alteradas pela gestão: JPEG/PNG até 2 MB."""
    if not arquivo or arquivo.size > limite_bytes:
        return False
    try:
        arquivo.seek(0)
        imagem = Image.open(arquivo)
        imagem.verify()
        arquivo.seek(0)
        return imagem.format in {'JPEG', 'PNG'}
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        arquivo.seek(0)
        return False

def login_view(request):
    #se o usuário clicou no botão entrar então ele enviou um formulário
    if request.method == 'POST':
        email = request.POST.get('email')
        senha = request.POST.get('senha')

        #checando se email e senha batem com os do banco, a função autenticate ja faz o hash p comparação
        usuario = authenticate(request, username=email, password=senha)

        if usuario is not None:
            if usuario.is_aprovado or usuario.is_superuser:
                auth_login(request, usuario) #inicia a sessão e cria o cookie de login
                messages.info(request, 'Logado com sucesso!')
                return redirect('home')
            else:
                #senha certa mas a instituição ainda não aprovou
                messages.warning(request, 'Sua conta ainda aguarda aprovação da instituição.', extra_tags='pending')
        else:
            #senha ou email errados
            messages.error(request, 'Email ou senha incorretos.')

    #se a requisição for GET (o usuário apenas digitou o site no navegador), mostra a tela vazia
    return render(request, 'usuarios/login.html')


@login_required(login_url='login')
def logout_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    auth_logout(request)
    messages.success(request, 'Sessão encerrada. Você já pode entrar com outro perfil.')
    return redirect('login')

#o login requiered protege a página, se não estiver logado, vai pro login
@login_required(login_url='login')
def painel_home(request):
    usuario = request.user
    
    if hasattr(usuario, 'instituicao') or usuario.is_superuser:
        return render(request, 'usuarios/home_instituicao.html', obter_contexto_monitoramento())

    elif hasattr(usuario, 'motorista'):
        motorista = usuario.motorista
        processar_rotas_sem_gps(motorista_id=motorista.pk)
        
        #busca a rota ativa (se existir)
        rota_ativa = Rota.objects.filter(
            motorista=motorista, ativa=True,
        ).select_related('veiculo').first()
        ultima_localizacao = (
            rota_ativa.coordenadas.order_by('-timestamp').first()
            if rota_ativa else None
        )
        
        #busca veículos autorizados para o motorista
        veiculos = motorista.veiculos.all()
        
        contexto = {
            'rota_ativa': rota_ativa,
            'ultima_localizacao': ultima_localizacao,
            'veiculos': veiculos
        }
        return render(request, 'usuarios/home_motorista.html', contexto)

    elif hasattr(usuario, 'responsavel'):
        meus_alunos = Aluno.objects.filter(responsavel=usuario.responsavel)
        
        contexto = {
            'alunos': meus_alunos
        }
        return render(request, 'usuarios/home_responsavel.html', contexto)

    # Caso o usuário não tenha perfil (erro de cadastro)
    return render(request, 'usuarios/home_generica.html')

def cadastro_responsavel(request):
    if request.method == 'POST':
        nome = request.POST.get('first_name', '').strip()
        sobrenome = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        cpf = request.POST.get('cpf', '')
        senha = request.POST.get('senha', '')
        confirmar_senha = request.POST.get('confirmar_senha', '')
        foto = request.FILES.get('foto_perfil')
        cor_avatar = request.POST.get('cor_avatar', '#1d4ed8')


        if len(nome) < 2 or len(nome) > 50:
            messages.error(request, 'O nome deve ter entre 2 e 50 caracteres.')
            return render(request, 'usuarios/cadastro.html')
            
        if len(sobrenome) < 2 or len(sobrenome) > 100:
            messages.error(request, 'O sobrenome deve ter entre 2 e 100 caracteres.')
            return render(request, 'usuarios/cadastro.html')

        if senha != confirmar_senha:
            messages.error(request, 'As senhas não coincidem.')
            return render(request, 'usuarios/cadastro.html')

        if not _senha_valida(senha):
            messages.error(request, 'A senha deve ter no mínimo 8 caracteres, letras maiúsculas e minúsculas, número e símbolo.')
            return render(request, 'usuarios/cadastro.html')

        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, 'Digite um formato de e-mail válido.')
            return render(request, 'usuarios/cadastro.html')

        #tirando traços e pontos caso o usuario tenha digitado
        cpf_limpo = re.sub(r'[^0-9]', '', cpf)
        if len(cpf_limpo) != 11:
            messages.error(request, 'O CPF deve conter exatamente 11 números.')
            return render(request, 'usuarios/cadastro.html')

        #verifica se o e-mail ou CPF já existem no banco
        if Usuario.objects.filter(email=email).exists():
            messages.error(request, 'Este e-mail já está cadastrado.')
            return render(request, 'usuarios/cadastro.html')
            
        if Responsavel.objects.filter(cpf=cpf_limpo).exists():
            messages.error(request, 'Este CPF já está cadastrado no sistema.')
            return render(request, 'usuarios/cadastro.html')

        if foto and not _imagem_valida(foto):
            messages.error(request, 'Envie uma foto válida em JPEG, PNG ou WebP com até 5 MB.')
            return render(request, 'usuarios/cadastro.html')

        cores_validas = {cor for cor, _ in Responsavel.CORES_AVATAR}
        if cor_avatar not in cores_validas:
            cor_avatar = '#1d4ed8'

        try:
            with transaction.atomic():
                #cria o login
                novo_usuario = Usuario.objects.create_user(
                    username=email,
                    email=email,
                    password=senha,
                    first_name=nome,
                    last_name=sobrenome
                )
                
                #cria o perfil e amarra ao login
                Responsavel.objects.create(usuario=novo_usuario, cpf=cpf_limpo, foto_perfil=foto, cor_avatar=cor_avatar)

            messages.info(request, 'Cadastro realizado com sucesso!')
            messages.success(request, 'Sua conta aguarda aprovação da instituição.', extra_tags='pending')
            return redirect('login')

        except Exception:
            messages.error(request, 'Não foi possível concluir o cadastro. Verifique os dados enviados e tente novamente.')
            return render(request, 'usuarios/cadastro.html')

    return render(request, 'usuarios/cadastro.html')

@login_required(login_url='login')
def painel_instituicao_aprovacoes(request):
    # Trava de segurança
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')

    # Busca todo mundo que o is_aprovado é False
    responsaveis = Responsavel.objects.filter(usuario__is_aprovado=False)
    motoristas = Motorista.objects.filter(usuario__is_aprovado=False)
    alunos = Aluno.objects.filter(is_aprovado=False)

    contexto = {
        'responsaveis_pendentes': responsaveis,
        'motoristas_pendentes': motoristas,
        'alunos_pendentes': alunos,
    }
    return render(request, 'usuarios/painel_aprovacoes.html', contexto)

@login_required(login_url='login')
def aprovar_cadastro(request, tipo, obj_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')

    if tipo == 'responsavel':
        obj = get_object_or_404(Responsavel, id=obj_id)
        obj.usuario.is_aprovado = True
        obj.usuario.save()
    elif tipo == 'motorista':
        obj = get_object_or_404(Motorista, id=obj_id)
        obj.usuario.is_aprovado = True
        obj.usuario.save()
    elif tipo == 'aluno':
        obj = get_object_or_404(Aluno, id=obj_id)
        obj.is_aprovado = True
        obj.save()
    else:
        return redirect('painel_aprovacoes')

    messages.success(request, f"Cadastro aprovado com sucesso!")
    return redirect('painel_aprovacoes')

@login_required(login_url='login')
def reprovar_cadastro(request, tipo, obj_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')

    if tipo == 'responsavel':
        obj = get_object_or_404(Responsavel, id=obj_id)
        obj.usuario.delete() 
    elif tipo == 'motorista':
        obj = get_object_or_404(Motorista, id=obj_id)
        obj.usuario.delete()
    elif tipo == 'aluno':
        obj = get_object_or_404(Aluno, id=obj_id)
        obj.delete()
    else:
        return redirect('painel_aprovacoes')

    messages.error(request, f"Cadastro rejeitado e removido do sistema.")
    return redirect('painel_aprovacoes')

@login_required(login_url='login')
def painel_usuarios_ativos(request):
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')
    
    return render(request, 'usuarios/painel_usuarios.html')


def _usuario_json(tipo, obj):
    if tipo == 'aluno':
        foto = obj.foto_perfil
        dados = {'id': obj.pk, 'nome': obj.nome, 'idade': obj.idade,
                 'responsavel': str(obj.responsavel.usuario.get_full_name()),
                 'responsavel_id': obj.responsavel_id,
                 'email': obj.responsavel.usuario.email,
                 'foto': foto.url if foto else '', 'aprovado': obj.is_aprovado,
                 'termo_consentimento': obj.termo_consentimento}
    else:
        usuario = obj.usuario
        foto = obj.foto_perfil
        dados = {'id': obj.pk, 'first_name': usuario.first_name,
                 'last_name': usuario.last_name, 'nome': usuario.get_full_name(),
                 'email': usuario.email, 'cpf': obj.cpf,
                 'foto': foto.url if foto else '', 'aprovado': usuario.is_aprovado}
        if tipo == 'responsavel':
            dados['cor_avatar'] = obj.cor_avatar
    return dados


@login_required(login_url='login')
def api_usuarios(request, tipo, obj_id=None):
    """CRUD JSON usado pela tela institucional; mantém regras e dados no servidor."""
    if not hasattr(request.user, 'instituicao'):
        return JsonResponse({'erro': 'Acesso permitido apenas à instituição.'}, status=403)
    if tipo not in {'aluno', 'motorista', 'responsavel'}:
        return JsonResponse({'erro': 'Categoria inválida.'}, status=404)
    model = {'aluno': Aluno, 'motorista': Motorista, 'responsavel': Responsavel}[tipo]
    qs = model.objects.all()
    if tipo == 'aluno':
        qs = qs.filter(is_aprovado=True).select_related('responsavel__usuario').order_by('nome')
    else:
        qs = qs.filter(usuario__is_aprovado=True).select_related('usuario').order_by('usuario__first_name', 'usuario__last_name')

    if request.method == 'GET' and obj_id is None:
        termo = request.GET.get('q', '').strip()
        if termo:
            condicao = Q(nome__icontains=termo) | Q(responsavel__usuario__first_name__icontains=termo) | Q(responsavel__usuario__last_name__icontains=termo) | Q(responsavel__usuario__email__icontains=termo) if tipo == 'aluno' else Q(usuario__first_name__icontains=termo) | Q(usuario__last_name__icontains=termo) | Q(usuario__email__icontains=termo) | Q(cpf__icontains=termo)
            if termo.isdigit():
                condicao |= Q(pk=int(termo))
            qs = qs.filter(condicao)
        paginator = Paginator(qs, 8)
        try:
            page = paginator.page(request.GET.get('page', 1))
        except (EmptyPage, TypeError, ValueError):
            page = paginator.page(paginator.num_pages or 1)
        return JsonResponse({'results': [_usuario_json(tipo, item) for item in page.object_list],
                             'page': page.number, 'pages': paginator.num_pages,
                             'total': paginator.count})
    if request.method == 'GET' and obj_id is not None:
        return JsonResponse(_usuario_json(tipo, get_object_or_404(qs, pk=obj_id)))
    if request.method not in {'POST', 'DELETE'}:
        return HttpResponseNotAllowed(['GET', 'POST', 'DELETE'])

    if request.method == 'DELETE':
        item = get_object_or_404(qs, pk=obj_id)
        if tipo == 'responsavel' and item.alunos.exists():
            return JsonResponse({'erro': 'Não é possível excluir um responsável que ainda possui alunos vinculados.'}, status=409)
        if tipo == 'motorista':
            from transporte.models import Rota
            if Rota.objects.filter(motorista=item, ativa=True).exists():
                return JsonResponse({'erro': 'Não é possível excluir um motorista com rota ativa.'}, status=409)
        if tipo == 'aluno':
            from transporte.models import Rota
            if item.eventos.exists():
                return JsonResponse({'erro': 'Não é possível excluir este aluno porque há eventos de transporte associados.'}, status=409)
            if Rota.objects.filter(ativa=True, veiculo__alunos_autorizados=item).exists():
                return JsonResponse({'erro': 'Não é possível excluir um aluno vinculado a uma rota ativa.'}, status=409)
        if tipo in {'motorista', 'responsavel'}:
            item.usuario.delete()
        else:
            item.delete()
        return JsonResponse({'mensagem': 'Usuário excluído com sucesso.'})

    criando = obj_id is None
    if not criando:
        item = get_object_or_404(qs, pk=obj_id)
    data = request.POST
    nome, sobrenome = data.get('first_name', '').strip(), data.get('last_name', '').strip()
    foto = request.FILES.get('foto_perfil')
    if foto and not (_imagem_valida(foto) if criando else _imagem_perfil_edicao_valida(foto)):
        mensagem = 'Envie uma imagem PNG ou JPEG válida com no máximo 2 MB.' if not criando else 'A foto deve ser JPEG, PNG ou WebP válida e ter até 5 MB.'
        return JsonResponse({'erro': mensagem}, status=400)
    try:
        with transaction.atomic():
            if tipo == 'aluno':
                nome_aluno = data.get('nome', '').strip()
                try:
                    idade = int(data.get('idade', ''))
                except (TypeError, ValueError):
                    idade = 0
                if len(nome_aluno) < 2 or len(nome_aluno) > 100 or not 2 <= idade <= 30:
                    return JsonResponse({'erro': 'Informe nome válido e idade entre 2 e 30 anos.'}, status=400)
                if criando:
                    if not data.get('termo_consentimento') or not foto or not data.get('foto_base64'):
                        return JsonResponse({'erro': 'Consentimento, captura facial e foto de perfil são obrigatórios para cadastrar aluno.'}, status=400)
                    try:
                        formato, imagem_b64 = data['foto_base64'].split(';base64,', 1)
                        extensao = formato.split('/')[-1].lower()
                        if extensao not in {'jpeg', 'png'}:
                            raise ValueError
                        bytes_faciais = base64.b64decode(imagem_b64, validate=True)
                        if len(bytes_faciais) > 8 * 1024 * 1024:
                            raise ValueError
                    except (ValueError, TypeError):
                        return JsonResponse({'erro': 'A captura facial deve ser uma imagem JPEG ou PNG válida, de até 8 MB.'}, status=400)
                    from alunos.views import codificar_foto_aluno
                    try:
                        dados_faciais = codificar_foto_aluno(ContentFile(bytes_faciais, name=f'captura_faciais.{extensao}'))
                    except ValueError as exc:
                        return JsonResponse({'erro': str(exc)}, status=400)
                    responsavel = get_object_or_404(Responsavel, pk=data.get('responsavel_id'), usuario__is_aprovado=True)
                    item = Aluno(nome=nome_aluno, idade=idade, responsavel=responsavel,
                                 dados_faciais=dados_faciais, termo_consentimento=True, is_aprovado=True)
                else:
                    item.nome, item.idade = nome_aluno, idade
                if foto:
                    item.foto_perfil = foto
                item.save()
            else:
                email = data.get('email', '').strip().lower()
                cpf = re.sub(r'\D', '', data.get('cpf', ''))
                if not nome or not sobrenome or len(nome) > 150 or len(sobrenome) > 150:
                    return JsonResponse({'erro': 'Informe nome e sobrenome (até 150 caracteres).'}, status=400)
                try:
                    validate_email(email)
                except ValidationError:
                    return JsonResponse({'erro': 'Informe um e-mail válido.'}, status=400)
                if len(cpf) != 11 or model.objects.filter(cpf=cpf).exclude(pk=None if criando else item.pk).exists():
                    return JsonResponse({'erro': 'CPF inválido ou já cadastrado.'}, status=400)
                usuario_atual = None if criando else item.usuario
                if Usuario.objects.filter(email=email).exclude(pk=None if criando else usuario_atual.pk).exists():
                    return JsonResponse({'erro': 'Este e-mail já está cadastrado.'}, status=400)
                if criando:
                    senha = data.get('senha', '')
                    if not _senha_valida(senha) or not foto:
                        return JsonResponse({'erro': 'Senha forte e foto de perfil são obrigatórias.'}, status=400)
                    usuario = Usuario.objects.create_user(username=email, email=email, password=senha,
                        first_name=nome, last_name=sobrenome, is_aprovado=True)
                    item = model(usuario=usuario, cpf=cpf, foto_perfil=foto)
                else:
                    usuario = item.usuario
                    usuario.first_name, usuario.last_name, usuario.email, usuario.username = nome, sobrenome, email, email
                    usuario.save()
                    item.cpf = cpf
                    if foto:
                        item.foto_perfil = foto
                item.save()
        return JsonResponse({'mensagem': 'Cadastro salvo com sucesso.', 'item': _usuario_json(tipo, item)}, status=201 if criando else 200)
    except Exception as exc:
        if str(exc) and exc.__class__.__name__ in {'IntegrityError', 'ValidationError'}:
            return JsonResponse({'erro': 'Não foi possível salvar. Verifique se e-mail e CPF são únicos.'}, status=400)
        return JsonResponse({'erro': 'Não foi possível salvar os dados. Tente novamente.'}, status=400)


@login_required(login_url='login')
def api_redefinir_senha_usuario(request, tipo, obj_id):
    if not hasattr(request.user, 'instituicao'):
        return JsonResponse({'erro': 'Acesso permitido apenas à instituição.'}, status=403)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if tipo not in {'motorista', 'responsavel'}:
        return JsonResponse({'erro': 'A redefinição de senha não está disponível para esta categoria.'}, status=400)
    usuario = get_object_or_404(Usuario, **{
        'is_aprovado': True,
        f'{tipo}__pk': obj_id,
    })
    senha = request.POST.get('senha', '')
    confirmar_senha = request.POST.get('confirmar_senha', '')
    if senha != confirmar_senha:
        return JsonResponse({'erro': 'As senhas não coincidem.'}, status=400)
    if not _senha_valida(senha):
        return JsonResponse({'erro': 'A senha deve ter ao menos 8 caracteres, letras maiúsculas e minúsculas, número e símbolo.'}, status=400)
    usuario.set_password(senha)
    usuario.save(update_fields=['password'])
    return JsonResponse({'mensagem': 'Senha redefinida com sucesso.'})

@login_required(login_url='login')
def cadastrar_motorista(request):
    if not hasattr(request.user, 'instituicao'):
        messages.error(request, 'Apenas a instituição pode cadastrar motoristas.')
        return redirect('home')

    if request.method == 'POST':
        nome = request.POST.get('first_name', '').strip()
        sobrenome = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        cpf = re.sub(r'\D', '', request.POST.get('cpf', ''))
        senha = request.POST.get('senha', '')
        foto = request.FILES.get('foto_perfil')

        erros = []
        if not nome or len(nome) > 150 or not sobrenome or len(sobrenome) > 150:
            erros.append('Informe nome e sobrenome (até 150 caracteres cada).')
        try:
            validate_email(email)
        except ValidationError:
            erros.append('Informe um e-mail válido.')
        if len(cpf) != 11:
            erros.append('O CPF deve conter 11 números.')
        if Usuario.objects.filter(email=email).exists():
            erros.append('Este e-mail já está cadastrado.')
        if Motorista.objects.filter(cpf=cpf).exists():
            erros.append('Este CPF já está cadastrado.')
        if not _senha_valida(senha):
            erros.append('A senha deve ter ao menos 8 caracteres, letras maiúsculas e minúsculas, número e símbolo.')
        if not _imagem_valida(foto):
            erros.append('Envie uma foto JPEG, PNG ou WebP válida com até 5 MB.')

        if erros:
            for erro in erros:
                messages.error(request, erro)
            return render(request, 'usuarios/cadastrar_motorista.html')

        try:
            with transaction.atomic():
                usuario = Usuario.objects.create_user(
                    username=email,
                    email=email,
                    password=senha,
                    first_name=nome,
                    last_name=sobrenome,
                    is_aprovado=True,
                )
                Motorista.objects.create(usuario=usuario, cpf=cpf, foto_perfil=foto)
        except Exception:
            messages.error(request, 'Não foi possível cadastrar o motorista. Verifique os dados e tente novamente.')
            return render(request, 'usuarios/cadastrar_motorista.html')

        messages.success(request, 'Motorista cadastrado e aprovado. Agora você pode vinculá-lo a um ou mais veículos.')
        return redirect('painel_usuarios')

    return render(request, 'usuarios/cadastrar_motorista.html')

@login_required(login_url='login')
def deletar_usuario(request, tipo, obj_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')

    if tipo == 'responsavel':
        get_object_or_404(Responsavel, id=obj_id).usuario.delete()
    elif tipo == 'motorista':
        get_object_or_404(Motorista, id=obj_id).usuario.delete()
    elif tipo == 'aluno':
        get_object_or_404(Aluno, id=obj_id).delete()

    messages.error(request, f"Usuário excluído com sucesso.")
    return redirect('painel_usuarios')
