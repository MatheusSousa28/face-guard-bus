import json
from django.shortcuts import redirect, render
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from .models import Rota, Localizacao
from django.contrib import messages
from monitoramento.models import Evento 
import base64
import numpy as np
from django.core.files.base import ContentFile
import face_recognition

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
def api_posicao_onibus(request, veiculo_id):
    usuario = request.user
    
    #acesso total p superuser/instituição
    is_admin = hasattr(usuario, 'instituicao') or usuario.is_superuser
    
    #responsaveis so podem ver rotas de seus filhos
    pode_ver = False
    
    if is_admin:
        pode_ver = True
    elif hasattr(usuario, 'responsavel'):
        # Verifica se algum filho deste responsável está embarcado neste veículo
        filhos_no_veiculo = Evento.objects.filter(
            rota__veiculo_id=veiculo_id,
            rota__ativa=True,
            aluno__responsavel=usuario.responsavel,
            tipo='embarque'
        ).exclude(
            #excluímos se o aluno já tiver um evento de desembarque posterior
            id__in=Evento.objects.filter(aluno__responsavel=usuario.responsavel, tipo='desembarque').values('id')
        ).exists()
        
        if filhos_no_veiculo:
            pode_ver = True

    #entrega da localização apenas se autorizado
    if pode_ver:
        rota_ativa = Rota.objects.filter(veiculo_id=veiculo_id, ativa=True).first()
        if rota_ativa:
            ultima_posicao = Localizacao.objects.filter(rota=rota_ativa).order_by('-timestamp').first()
            if ultima_posicao:
                return JsonResponse({
                    'status': 'online',
                    'latitude': float(ultima_posicao.latitude),
                    'longitude': float(ultima_posicao.longitude),
                    'atualizado_em': ultima_posicao.timestamp.strftime('%H:%M:%S')
                })
    
    return JsonResponse({'status': 'acesso_negado'}, status=403)

@login_required(login_url='login')
def monitoramento_instituicao(request):
    # Apenas escola ou admin
    if not (hasattr(request.user, 'instituicao') or request.user.is_superuser):
        return redirect('home')
        
    rotas_ativas = Rota.objects.filter(ativa=True).select_related('veiculo', 'motorista')
    return render(request, 'transporte/monitoramento_geral.html', {'rotas': rotas_ativas})

@login_required(login_url='login')
def api_todas_posicoes(request):
    # Retorna a localização de todos os ônibus que estão em rota no momento
    # Autorização penas para Instituição ou Admin
    if not (hasattr(request.user, 'instituicao') or request.user.is_superuser):
        return JsonResponse({'error': 'Acesso negado'}, status=403)

    rotas_ativas = Rota.objects.filter(ativa=True)
    lista_posicoes = []

    for rota in rotas_ativas:
        ultima_pos = Localizacao.objects.filter(rota=rota).order_by('-timestamp').first()
        if ultima_pos:
            lista_posicoes.append({
                'veiculo_id': rota.veiculo.id,
                'placa': rota.veiculo.placa,
                'modelo': rota.veiculo.modelo,
                'motorista': rota.motorista.usuario.get_full_name(),
                'latitude': float(ultima_pos.latitude),
                'longitude': float(ultima_pos.longitude),
                'atualizado_em': ultima_pos.timestamp.strftime('%H:%M:%S')
            })

    return JsonResponse({'veiculos': lista_posicoes})

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
                # Busca o último evento deste aluno nesta rota específica
                ultimo_evento = Evento.objects.filter(
                    rota=rota_ativa, 
                    aluno=aluno_reconhecido
                ).order_by('-data_hora').first()

                # Se não tem evento ou o último foi desembarque -> Novo Embarque
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

                return JsonResponse({
                    'status': 'sucesso',
                    'tipo': tipo_evento.capitalize(),
                    'aluno': aluno_reconhecido.nome
                })
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