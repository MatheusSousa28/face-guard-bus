from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Usuario, Responsavel 
from django.db import transaction
import re
from alunos.models import Aluno

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

#o login requiered protege a página, se não estiver logado, vai pro login
@login_required(login_url='login')
def painel_home(request):
    usuario = request.user
    
    if hasattr(usuario, 'instituicao') or usuario.is_superuser:
        return render(request, 'usuarios/home_instituicao.html')

    elif hasattr(usuario, 'motorista'):
        return render(request, 'usuarios/home_motorista.html')

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
        email = request.POST.get('email', '').strip()
        cpf = request.POST.get('cpf', '')
        senha = request.POST.get('senha')
        confirmar_senha = request.POST.get('confirmar_senha')        
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

        regex_senha = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$'
        if not re.match(regex_senha, senha):
            messages.error(request, 'A senha deve ter no mínimo 8 caracteres, contendo maiúsculas, minúsculas, números e pelo menos um símbolo (@$!%*?&).')
            return redirect('cadastro')

        regex_email = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(regex_email, email):
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

        except Exception as e:
            #se der erro em uma das criações, dá rollback
            messages.error(request, f'Erro interno ao criar cadastro: {str(e)}')
            return redirect('cadastro')

    return render(request, 'usuarios/cadastro.html')
