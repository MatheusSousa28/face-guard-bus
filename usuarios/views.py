from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login
from django.contrib import messages

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
                return redirect('painel_home')
            else:
                #senha certa mas a instituição ainda não aprovou
                messages.warning(request, 'Sua conta ainda aguarda aprovação da instituição.')
        else:
            #senha ou email errados
            messages.error(request, 'Email ou senha incorretos.')

    # Se a requisição for GET (o usuário apenas digitou o site no navegador), mostra a tela vazia
    return render(request, 'usuarios/login.html')