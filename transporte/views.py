import json
from django.shortcuts import redirect, render, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from .models import Rota, Localizacao, Veiculo
from usuarios.models import Motorista
from django.contrib import messages
from monitoramento.models import Evento 
import base64
import numpy as np
from django.core.files.base import ContentFile
import face_recognition
from datetime import timedelta

@login_required(login_url='login')
def iniciar_rota(request):
    if request.method == 'POST':
        motorista_logado = request.user.motorista
        veiculo_id = request.POST.get('veiculo_id')

        if not veiculo_id:
            messages.error(request, "Por favor, selecione um veículo para iniciar a rota.")
            return redirect('home')

        #busca o veículo específico que o motorista escolheu, 
        # mas garante que faz parte da lista de autorizados dele.
        veiculo = motorista_logado.veiculos.filter(id=veiculo_id).first()

        if not veiculo:
            messages.error(request, "Veículo inválido ou não autorizado para o seu perfil.")
            return redirect('home')

        # Verifica se já não existe uma rota ativa
        rota_ativa = Rota.objects.filter(motorista=motorista_logado, ativa=True).first()
        
        if not rota_ativa:
            # Cria a nova Rota com o veículo selecionado!
            rota_ativa = Rota.objects.create(
                veiculo=veiculo,
                motorista=motorista_logado,
                inicio=timezone.now(),
                ativa=True
            )
            messages.success(request, f"Rota iniciada com sucesso no veículo {veiculo.placa}!")
        else:
            messages.warning(request, "Você já possui uma rota em andamento.")
        
    return redirect('home')

@login_required(login_url='login')
def finalizar_rota(request):
    if request.method == 'POST':
        motorista_logado = request.user.motorista
        #busca a rota que está marcada como ativa
        rota_ativa = Rota.objects.filter(motorista=motorista_logado, ativa=True).first()

        alunos_embarcados = Evento.objects.filter(rota=rota_ativa, tipo='embarque').count()
        alunos_desembarcados = Evento.objects.filter(rota=rota_ativa, tipo='desembarque').count()

        if alunos_embarcados > alunos_desembarcados:
            messages.error(request, "Atenção! Ainda existem alunos dentro do veículo.")
            return redirect('home')
        
        if rota_ativa:
            rota_ativa.ativa = False
            rota_ativa.fim = timezone.now()
            rota_ativa.save()
            messages.success(request, "Rota finalizada com sucesso. Bom descanso!")
        else:
            messages.error(request, "Não foi encontrada nenhuma rota ativa para encerrar.")
            
    return redirect('home')

@csrf_exempt #desativando a proteção de formulário para facilitar a API via JS
def receber_localizacao(request):
    #api que recebe a loclização do celular
    if request.method == 'POST':
        try:
            #lendo o JSON que o JS do celular enviou
            dados = json.loads(request.body)
            lat = dados.get('latitude')
            lng = dados.get('longitude')
            
            #identifica o motorista logado e pega a rota ativa dele
            if request.user.is_authenticated and hasattr(request.user, 'motorista'):
                rota_ativa = Rota.objects.filter(motorista=request.user.motorista, ativa=True).first()
                
                if rota_ativa:
                    # Salva o ponto do GPS no banco de dados!
                    Localizacao.objects.create(
                        rota=rota_ativa,
                        latitude=lat,
                        longitude=lng
                    )
                    return JsonResponse({'status': 'sucesso'})
            
            return JsonResponse({'status': 'erro', 'mensagem': 'Nenhuma rota ativa encontrada.'}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'erro', 'mensagem': str(e)}, status=500)
            
    return JsonResponse({'status': 'metodo_invalido'}, status=405)

@login_required(login_url='login')
def monitoramento_instituicao(request):
    # Apenas escola ou admin
    if not (hasattr(request.user, 'instituicao') or request.user.is_superuser):
        return redirect('home')
        
    rotas_ativas = Rota.objects.filter(ativa=True).select_related('veiculo', 'motorista')
    return render(request, 'transporte/monitoramento_geral.html', {'rotas': rotas_ativas})

#api que detecta a face do aluno no embarque/desembarque
@csrf_exempt
def api_reconhecimento(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            img_base64 = data.get('imagem')
            
            #Recupera a rota ativa do motorista logado
            rota_ativa = Rota.objects.filter(motorista__usuario=request.user, ativa=True).first()
            if not rota_ativa:
                return JsonResponse({'status': 'erro', 'mensagem': 'Nenhuma rota ativa.'}, status=400)

            #Decodifica a imagem recebida da catraca
            format, imgstr = img_base64.split(';base64,')
            ext = format.split('/')[-1]
            arquivo_imagem = ContentFile(base64.b64decode(imgstr), name=f"temp_captura.{ext}")

            #Carrega a imagem e extrai a biometria (encoding)
            imagem_carregada = face_recognition.load_image_file(arquivo_imagem)
            encodings_capturados = face_recognition.face_encodings(imagem_carregada)

            if not encodings_capturados:
                return JsonResponse({'status': 'nenhum_rosto'})

            encoding_atual = encodings_capturados[0]

            #Busca apenas alunos autorizados para este veículo para otimizar
            alunos_autorizados = rota_ativa.veiculo.alunos_autorizados.all()
            
            aluno_reconhecido = None
            for aluno in alunos_autorizados:
                
                dados_brutos = aluno.dados_faciais
                
                #Se o banco devolveu um texto, converte de volta para lista
                if isinstance(dados_brutos, str):
                    dados_brutos = json.loads(dados_brutos)
                
                #Transforma em array NumPy garantindo que são números decimais
                conhecido_encoding = np.array(dados_brutos, dtype=float)
                
                #Compara as faces
                match = face_recognition.compare_faces([conhecido_encoding], encoding_atual, tolerance=0.5)
                
                if match[0]:
                    aluno_reconhecido = aluno
                    break

            if aluno_reconhecido:
                if aluno_reconhecido:
                # Busca o último evento deste aluno nesta rota específica
                    ultimo_evento = Evento.objects.filter(
                        rota=rota_ativa, 
                        aluno=aluno_reconhecido
                    ).order_by('-data_hora').first()

                    #se o mesmo aluno registrou um evento muito recentemente, o sistema bloqueia a ação
                    if ultimo_evento:
                        tempo_passado = timezone.now() - ultimo_evento.data_hora
                        # Define a carência em segundos (Ex: 60 segundos para a demonstração)
                        # No mundo real, você colocaria algo como 300 (5 minutos)
                        if tempo_passado.total_seconds() < 60:
                            return JsonResponse({
                                'status': 'carencia',
                                'aluno': aluno_reconhecido.nome
                            })

                    if not ultimo_evento or ultimo_evento.tipo == 'desembarque':
                        tipo_evento = 'embarque'
                    else:
                        tipo_evento = 'desembarque'

                    # Cria o registro do evento
                    Evento.objects.create(
                        rota=rota_ativa,
                        aluno=aluno_reconhecido,
                        tipo=tipo_evento,
                        foto_capturada=arquivo_imagem,
                        autorizado=True
                    )
            else:
                # Caso a face não seja de um aluno autorizado ou seja desconhecida
                Evento.objects.create(
                    rota=rota_ativa,
                    tipo='desconhecido',
                    foto_capturada=arquivo_imagem,
                    autorizado=False
                )
                return JsonResponse({'status': 'desconhecido'})

        except Exception as e:
            return JsonResponse({'status': 'erro', 'mensagem': str(e)}, status=500)

    return JsonResponse({'status': 'metodo_invalido'}, status=405)

@login_required(login_url='login')
def simulador_catraca(request):
    #view apenas para renderizar a tela preta com a webcam
    if not hasattr(request.user, 'motorista'):
        messages.error(request, "Acesso Negado: Apenas motoristas logados podem operar a catraca do veículo.")
        return redirect('home')
    return render(request, 'transporte/catraca.html')

@login_required(login_url='login')
def api_frota_mapa_unificada(request):
    usuario = request.user
    is_admin = hasattr(usuario, 'instituicao') or usuario.is_superuser
    is_responsavel = hasattr(usuario, 'responsavel')

    # Proteção de acesso
    if not (is_admin or is_responsavel):
        return JsonResponse({'error': 'Acesso negado'}, status=403)

    rotas_ativas = Rota.objects.filter(ativa=True).select_related('veiculo', 'motorista', 'motorista__usuario')
    lista_veiculos = []

    for rota in rotas_ativas:
        ultima_pos = Localizacao.objects.filter(rota=rota).order_by('-timestamp').first()
        if not ultima_pos:
            continue

        # Busca todos os eventos dessa rota
        eventos_rota = Evento.objects.filter(rota=rota).select_related('aluno').order_by('data_hora')
        
        # Filtro Rigoroso: Se for Pai, corta os eventos para sobrar APENAS os dos filhos dele
        if is_responsavel and not is_admin:
            eventos_rota = eventos_rota.filter(aluno__responsavel=usuario.responsavel)

        # Descobre o status atual de cada aluno a bordo (varrendo do mais antigo pro mais novo)
        status_atual_alunos = {}
        for ev in eventos_rota:
            if ev.aluno:
                status_atual_alunos[ev.aluno] = ev

        # Separa apenas quem está a bordo AGORA
        alunos_abordo = []
        for aluno, ev in status_atual_alunos.items():
            if ev.tipo == 'embarque':
                alunos_abordo.append({
                    'nome': aluno.nome,
                    'foto': aluno.foto_perfil.url if aluno.foto_perfil else '',
                    'hora': ev.data_hora.strftime('%H:%M:%S')
                })

        #o pai NÃO VÊ o ônibus no mapa se o filho dele não estiver a bordo
        if is_responsavel and not is_admin and not alunos_abordo:
            continue

        # Monta o histórico completo de entrada/saída (Pais veem só dos filhos, Instituição vê de todos)
        historico = []
        for ev in eventos_rota.order_by('-data_hora'):
            if ev.aluno:
                historico.append({
                    'nome': ev.aluno.nome,
                    'tipo': 'Embarcou' if ev.tipo == 'embarque' else 'Desembarcou',
                    'hora': ev.data_hora.strftime('%H:%M:%S')
                })

        # Prepara a foto do motorista
        motorista_foto = ''
        if rota.motorista and rota.motorista.foto_perfil:
            motorista_foto = rota.motorista.foto_perfil.url

        lista_veiculos.append({
            'veiculo_id': rota.veiculo.id,
            'placa': rota.veiculo.placa,
            'modelo': rota.veiculo.modelo,
            'motorista': rota.motorista.usuario.first_name if rota.motorista else 'Desconhecido',
            'motorista_foto': motorista_foto,
            'latitude': float(ultima_pos.latitude),
            'longitude': float(ultima_pos.longitude),
            'atualizado_em': ultima_pos.timestamp.strftime('%H:%M:%S'),
            'alunos_abordo': alunos_abordo,
            'historico': historico,
        })

    return JsonResponse({'veiculos': lista_veiculos})

@login_required(login_url='login')
def tela_mapa_unificado(request):
    return render(request, 'transporte/mapa_unificado.html')

@login_required(login_url='login')
def painel_veiculos(request):
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')
    veiculos = Veiculo.objects.all()
    return render(request, 'transporte/painel_veiculos.html', {'veiculos': veiculos})

@login_required(login_url='login')
def gerenciar_veiculo(request, id=None):
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')
    
    veiculo = get_object_or_404(Veiculo, id=id) if id else None
    motoristas = Motorista.objects.filter(usuario__is_aprovado=True)

    if request.method == 'POST':
        modelo = request.POST.get('modelo')
        capacidade = request.POST.get('capacidade')
        placa = request.POST.get('placa')
        cor = request.POST.get('cor')
        foto = request.FILES.get('foto')
        motoristas_ids = request.POST.getlist('motoristas') # Pega a lista de IDs dos checkboxes

        if not veiculo:
            veiculo = Veiculo.objects.create(modelo=modelo, capacidade=capacidade, placa=placa, cor=cor)
            messages.success(request, 'Veículo cadastrado com sucesso!')
        else:
            veiculo.modelo = modelo
            veiculo.capacidade = capacidade
            veiculo.placa = placa
            veiculo.cor = cor
            veiculo.save()
            messages.success(request, 'Veículo atualizado com sucesso!')

        if foto:
            veiculo.foto = foto
            veiculo.save()

        #salva todos os motoristas marcados de uma vez no banco
        veiculo.motoristas_autorizados.set(motoristas_ids)

        return redirect('painel_veiculos')

    return render(request, 'transporte/form_veiculo.html', {'veiculo': veiculo, 'motoristas': motoristas})

@login_required(login_url='login')
def deletar_veiculo(request, id):
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')
    veiculo = get_object_or_404(Veiculo, id=id)
    veiculo.delete()
    messages.error(request, 'Veículo removido do sistema.')
    return redirect('painel_veiculos')