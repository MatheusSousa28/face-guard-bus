from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect
import base64
import json
import io
import face_recognition
from django.core.files.base import ContentFile
from alunos.models import Aluno
import uuid


def codificar_foto_aluno(arquivo):
    """Valida imagem de rosto e retorna o vetor facial persistível."""
    arquivo.seek(0)
    imagem = face_recognition.load_image_file(arquivo)
    rostos = face_recognition.face_encodings(imagem)
    arquivo.seek(0)
    if len(rostos) != 1:
        raise ValueError('A foto deve conter exatamente um rosto.')
    return json.dumps(rostos[0].tolist())

@login_required(login_url='login')
def cadastro_aluno(request):
    #só Responsáveis podem acessar essa view
    if not hasattr(request.user, 'responsavel'):
        messages.error(request, "Apenas responsáveis têm permissão para cadastrar alunos.")
        return redirect('home')

    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        idade_str = request.POST.get('idade')
        foto_base64 = request.POST.get('foto_base64')
        termo = request.POST.get('termo')

        # Validações Iniciais
        if not termo:
            messages.error(request, "Aceite o termo de consentimento para realizar o cadastro.")
            return redirect('cadastro_aluno')

        if len(nome) < 2 or len(nome) > 50:
            messages.error(request, 'O nome deve ter entre 2 e 50 caracteres.')
            return redirect('cadastro_aluno')

        try:
            idade = int(idade_str) #converte para número
            if idade < 2 or idade > 30:
                messages.error(request, "O aluno deve ter no mínimo 2 anos e no máximo 30.")
                return redirect('cadastro_aluno')
        except (TypeError, ValueError):
            messages.error(request, "Idade inválida.")
            return redirect('cadastro_aluno')

        if not foto_base64:
            messages.error(request, "A captura da biometria facial é obrigatória.")
            return redirect('cadastro_aluno')

        if len(foto_base64) > 8_000_000:
            messages.error(request, 'A captura excede o tamanho máximo permitido.')
            return redirect('cadastro_aluno')

        #módulo de intelgiencia artificial e imagem
        try:
            #limpando o Base64 ex: 'data:image/jpeg;base64,/9j/4AAQSk...'
            formato, imgstr = foto_base64.split(';base64,', 1)
            extensao = formato.split('/')[-1] # Pega o 'jpeg' ou 'png'
            if extensao not in ('jpeg', 'png'):
                messages.error(request, 'A captura deve estar em JPEG ou PNG. Tente novamente.')
                return redirect('cadastro_aluno')
            
            #converte a string de volta para os bytes da imagem
            image_data = base64.b64decode(imgstr, validate=True)

            #carrega a imagem na memória para a bib ler
            imagem_memoria = face_recognition.load_image_file(io.BytesIO(image_data))
            
            #a IA procura rostos e gera as matrizes
            rostos_encontrados = face_recognition.face_encodings(imagem_memoria)

            #validação Biométrica Rigorosa
            if len(rostos_encontrados) == 0:
                messages.error(request, "Nenhum rosto detectado! Tente num local mais iluminado e sem óculos escuros.")
                return redirect('cadastro_aluno')
            elif len(rostos_encontrados) > 1:
                messages.error(request, "Atenção: Mais de um rosto detectado. A foto deve ser apenas do aluno.")
                return redirect('cadastro_aluno')

            #pega o primeiro e único rosto da lista, converte para lista comum e depois para JSON (Texto)
            vetor_128_numeros = json.dumps(rostos_encontrados[0].tolist())
            responsavel_logado = request.user.responsavel
            codigo_unico = uuid.uuid4().hex[:10] 
            nome_arquivo = f"aluno_{responsavel_logado.id}_{codigo_unico}.{extensao}"
            
            #salva o aluno no Banco de Dados
            novo_aluno = Aluno(
                nome=nome,
                idade=idade,
                responsavel=responsavel_logado,
                dados_faciais=vetor_128_numeros,
                termo_consentimento=True,
                is_aprovado=False #aguarda a escola
            )
            
            # Salva o arquivo de imagem físico na pasta media/
            novo_aluno.foto_perfil.save(nome_arquivo, ContentFile(image_data), save=False)
            novo_aluno.save()

            messages.success(request, "Biometria e Aluno cadastrados com sucesso! Aguarde aprovação.")
            return redirect('home')

        except Exception:
            messages.error(request, 'Não foi possível processar a captura facial. Verifique a imagem e tente novamente.')
            return redirect('cadastro_aluno')

    return render(request, 'alunos/cadastro_aluno.html')
