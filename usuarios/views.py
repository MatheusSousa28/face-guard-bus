from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseNotAllowed
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Usuario, Responsavel, Motorista
from .monitoramento import obter_contexto_monitoramento
from django.db import transaction
from django.utils import timezone
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
import re
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
                return redirect('home')
            else:
                #senha certa mas a instituição ainda não aprovou
                messages.warning(request, 'Sua conta ainda aguarda aprovação da instituição.')
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


        if len(nome) < 2 or len(nome) > 50:
            messages.error(request, 'O nome deve ter entre 2 e 50 caracteres.')
            return redirect('cadastro')
            
        if len(sobrenome) < 2 or len(sobrenome) > 100:
            messages.error(request, 'O sobrenome deve ter entre 2 e 100 caracteres.')
            return redirect('cadastro')

        if senha != confirmar_senha:
            messages.error(request, 'As senhas não coincidem.')
            return redirect('cadastro')

        if not _senha_valida(senha):
            messages.error(request, 'A senha deve ter no mínimo 8 caracteres, letras maiúsculas e minúsculas, número e símbolo.')
            return redirect('cadastro')

        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, 'Digite um formato de e-mail válido.')
            return redirect('cadastro')

        #tirando traços e pontos caso o usuario tenha digitado
        cpf_limpo = re.sub(r'[^0-9]', '', cpf)
        if len(cpf_limpo) != 11:
            messages.error(request, 'O CPF deve conter exatamente 11 números.')
            return redirect('cadastro')

        #verifica se o e-mail ou CPF já existem no banco
        if Usuario.objects.filter(email=email).exists():
            messages.error(request, 'Este e-mail já está cadastrado.')
            return redirect('cadastro')
            
        if Responsavel.objects.filter(cpf=cpf_limpo).exists():
            messages.error(request, 'Este CPF já está cadastrado no sistema.')
            return redirect('cadastro')

        if not _imagem_valida(foto):
            messages.error(request, 'Envie uma foto válida em JPEG, PNG ou WebP com até 5 MB.')
            return redirect('cadastro')

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
                Responsavel.objects.create(usuario=novo_usuario, cpf=cpf_limpo, foto_perfil=foto)

            messages.success(request, 'Cadastro realizado com sucesso! Aguarde a aprovação da instituição.')
            return redirect('login')

        except Exception:
            messages.error(request, 'Não foi possível concluir o cadastro. Verifique os dados enviados e tente novamente.')
            return redirect('cadastro')

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
    
    responsaveis = Responsavel.objects.filter(usuario__is_aprovado=True)
    motoristas = Motorista.objects.filter(usuario__is_aprovado=True)
    alunos = Aluno.objects.filter(is_aprovado=True)

    contexto = {
        'responsaveis': responsaveis,
        'motoristas': motoristas,
        'alunos': alunos,
    }
    return render(request, 'usuarios/painel_usuarios.html', contexto)

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
