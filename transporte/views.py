import json
from django.shortcuts import redirect, render, get_object_or_404
from django.http import HttpResponseNotAllowed, JsonResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from .models import Rota, Localizacao, Veiculo
from .services import (
    contar_alunos_a_bordo,
    obter_estado_gps,
    processar_rotas_sem_gps,
)
from usuarios.models import Motorista
from alunos.models import Aluno
from django.contrib import messages
from django.db import transaction
from monitoramento.models import Evento 
import base64
import binascii
import math
import numpy as np
from django.core.files.base import ContentFile
import face_recognition
from math import radians, sin, cos, sqrt, atan2
from PIL import Image, UnidentifiedImageError

@login_required(login_url='login')
def iniciar_rota(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not hasattr(request.user, 'motorista') or not request.user.is_aprovado:
        messages.error(request, 'Apenas motoristas aprovados podem iniciar rotas.')
        return redirect('home')

    veiculo_id = request.POST.get('veiculo_id')
    if not veiculo_id:
        messages.error(request, 'Por favor, selecione um veículo para iniciar a rota.')
        return redirect('home')

    try:
        with transaction.atomic():
            motorista = Motorista.objects.select_for_update().get(pk=request.user.motorista.pk)
            # O bloqueio evita duas solicitações simultâneas iniciando o mesmo veículo.
            veiculo = motorista.veiculos.select_for_update().filter(pk=veiculo_id).first()
            if not veiculo:
                messages.error(request, 'Veículo inválido ou não autorizado para o seu perfil.')
                return redirect('home')

            processar_rotas_sem_gps(motorista_id=motorista.pk)
            processar_rotas_sem_gps(veiculo_id=veiculo.pk)

            if Rota.objects.filter(motorista=motorista, ativa=True).exists():
                pendente = Rota.objects.filter(
                    motorista=motorista, ativa=True, interrompida=True,
                ).exists()
                if pendente:
                    messages.warning(request, 'Sua rota foi interrompida e aguarda revisão da instituição.')
                else:
                    messages.warning(request, 'Você já possui uma rota em andamento.')
                return redirect('home')
            if Rota.objects.filter(veiculo=veiculo, ativa=True).exists():
                pendente = Rota.objects.filter(
                    veiculo=veiculo, ativa=True, interrompida=True,
                ).exists()
                if pendente:
                    messages.error(request, 'Este veículo está reservado por uma rota interrompida que aguarda revisão.')
                else:
                    messages.error(request, 'Este veículo já possui uma rota em andamento.')
                return redirect('home')

            Rota.objects.create(
                veiculo=veiculo,
                motorista=motorista,
                inicio=timezone.now(),
                ativa=True,
            )
    except Motorista.DoesNotExist:
        messages.error(request, 'Perfil de motorista não encontrado.')
        return redirect('home')

    messages.success(request, f'Rota iniciada com sucesso no veículo {veiculo.placa}!')
    return redirect('home')

@login_required(login_url='login')
def finalizar_rota(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not hasattr(request.user, 'motorista') or not request.user.is_aprovado:
        messages.error(request, 'Apenas motoristas aprovados podem finalizar rotas.')
        return redirect('home')

    with transaction.atomic():
        processar_rotas_sem_gps(motorista_id=request.user.motorista.pk)
        rota_ativa = Rota.objects.select_for_update().filter(
            motorista=request.user.motorista, ativa=True
        ).first()
        if rota_ativa:
            if rota_ativa.interrompida:
                messages.error(request, 'Esta rota foi interrompida e precisa ser revisada pela instituição.')
                return redirect('home')
            alunos_abordo = contar_alunos_a_bordo(rota_ativa)
            if alunos_abordo:
                messages.error(request, f'Atenção! Ainda há {alunos_abordo} aluno(s) dentro do veículo.')
                return redirect('home')

            rota_ativa.ativa = False
            rota_ativa.fim = timezone.now()
            rota_ativa.save(update_fields=['ativa', 'fim'])
            messages.success(request, 'Rota finalizada com sucesso. Bom descanso!')
        else:
            messages.error(request, 'Não foi encontrada nenhuma rota ativa para encerrar.')

    return redirect('home')


@login_required(login_url='login')
def resolver_rota_interrompida(request, rota_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not (hasattr(request.user, 'instituicao') or request.user.is_superuser):
        messages.error(request, 'Apenas a instituição pode revisar uma rota interrompida.')
        return redirect('home')

    observacao = request.POST.get('observacao', '').strip()
    if not observacao or len(observacao) > 1000:
        messages.error(request, 'Informe uma observação válida para registrar a revisão da rota.')
        return redirect('home')
    if request.POST.get('confirmacao_seguranca') != 'on':
        messages.error(request, 'Confirme que a situação dos alunos foi verificada antes de encerrar a rota.')
        return redirect('home')

    with transaction.atomic():
        rota = Rota.objects.select_for_update().filter(
            pk=rota_id, ativa=True, interrompida=True,
        ).first()
        if not rota:
            messages.error(request, 'Esta rota não está mais aguardando revisão.')
            return redirect('home')
        agora = timezone.now()
        rota.ativa = False
        rota.fim = agora
        rota.resolvida_por = request.user
        rota.resolvida_em = agora
        rota.observacao_resolucao = observacao
        rota.save(update_fields=[
            'ativa', 'fim', 'resolvida_por', 'resolvida_em', 'observacao_resolucao',
        ])

    messages.success(request, 'A rota interrompida foi encerrada após revisão.')
    return redirect('home')

@login_required(login_url='login')
def receber_localizacao(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido.'}, status=405)
    if not hasattr(request.user, 'motorista') or not request.user.is_aprovado:
        return JsonResponse({'status': 'erro', 'mensagem': 'Apenas motoristas aprovados podem enviar GPS.'}, status=403)
    if request.content_type != 'application/json':
        return JsonResponse({'status': 'erro', 'mensagem': 'Envie as coordenadas em JSON.'}, status=415)

    try:
        dados = json.loads(request.body)
        lat = float(dados.get('latitude'))
        lng = float(dados.get('longitude'))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, AttributeError):
        return JsonResponse({'status': 'erro', 'mensagem': 'Coordenadas inválidas.'}, status=400)

    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        return JsonResponse({'status': 'erro', 'mensagem': 'Coordenadas fora do intervalo válido.'}, status=400)

    with transaction.atomic():
        processar_rotas_sem_gps(motorista_id=request.user.motorista.pk)
        rota_ativa = Rota.objects.select_for_update().filter(
            motorista=request.user.motorista, ativa=True, interrompida=False,
        ).first()
        if not rota_ativa:
            rota_interrompida = Rota.objects.filter(
                motorista=request.user.motorista, ativa=True, interrompida=True,
            ).exists()
            if rota_interrompida:
                return JsonResponse({
                    'status': 'interrompida',
                    'mensagem': 'A rota foi interrompida e aguarda revisão da instituição.',
                }, status=409)
            return JsonResponse({'status': 'erro', 'mensagem': 'Nenhuma rota ativa encontrada.'}, status=400)
        localizacao = Localizacao.objects.create(rota=rota_ativa, latitude=lat, longitude=lng)
    return JsonResponse({
        'status': 'sucesso',
        'atualizado_em': timezone.localtime(localizacao.timestamp).strftime('%H:%M:%S'),
    })

@login_required(login_url='login')
def monitoramento_instituicao(request):
    # Apenas escola ou admin
    if not (hasattr(request.user, 'instituicao') or request.user.is_superuser):
        return redirect('home')
        
    processar_rotas_sem_gps()
    rotas_ativas = Rota.objects.filter(
        ativa=True, interrompida=False,
    ).select_related('veiculo', 'motorista')
    return render(request, 'transporte/monitoramento_geral.html', {'rotas': rotas_ativas})

#api que detecta a face do aluno no embarque/desembarque
@login_required(login_url='login')
def api_reconhecimento(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido.'}, status=405)
    if not hasattr(request.user, 'motorista') or not request.user.is_aprovado:
        return JsonResponse({'status': 'erro', 'mensagem': 'Apenas motoristas aprovados podem operar a câmera.'}, status=403)
    if request.content_type != 'application/json':
        return JsonResponse({'status': 'erro', 'mensagem': 'Envie a captura em JSON.'}, status=415)

    try:
        data = json.loads(request.body)
        img_base64 = data.get('imagem')
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return JsonResponse({'status': 'erro', 'mensagem': 'Requisição inválida.'}, status=400)
    if not img_base64 or not isinstance(img_base64, str) or ';base64,' not in img_base64:
        return JsonResponse({'status': 'erro', 'mensagem': 'Imagem inválida.'}, status=400)
    if len(img_base64) > 8_000_000:
        return JsonResponse({'status': 'erro', 'mensagem': 'A captura excede o tamanho permitido.'}, status=413)

    processar_rotas_sem_gps(motorista_id=request.user.motorista.pk)
    rota_ativa = Rota.objects.filter(
        motorista=request.user.motorista, ativa=True, interrompida=False,
    ).select_related('veiculo').first()
    if not rota_ativa:
        if Rota.objects.filter(
            motorista=request.user.motorista, ativa=True, interrompida=True,
        ).exists():
            return JsonResponse({
                'status': 'interrompida',
                'mensagem': 'A rota foi interrompida e aguarda revisão da instituição.',
            }, status=409)
        return JsonResponse({'status': 'erro', 'mensagem': 'Nenhuma rota ativa.'}, status=400)

    formato, imgstr = img_base64.split(';base64,', 1)
    extensao = formato.removeprefix('data:image/')
    if extensao not in ('jpeg', 'png'):
        return JsonResponse({'status': 'erro', 'mensagem': 'Formato de imagem não permitido.'}, status=400)
    try:
        bytes_imagem = base64.b64decode(imgstr, validate=True)
        if len(bytes_imagem) > 6 * 1024 * 1024:
            return JsonResponse({'status': 'erro', 'mensagem': 'A captura excede o tamanho permitido.'}, status=413)
        arquivo_imagem = ContentFile(bytes_imagem, name=f'captura.{extensao}')
        imagem_carregada = face_recognition.load_image_file(arquivo_imagem)
        encodings_capturados = face_recognition.face_encodings(imagem_carregada)
    except (binascii.Error, ValueError, OSError):
        return JsonResponse({'status': 'erro', 'mensagem': 'A captura não é uma imagem válida.'}, status=400)

    if not encodings_capturados:
        return JsonResponse({'status': 'nenhum_rosto'})
    if len(encodings_capturados) > 1:
        return JsonResponse({
            'status': 'multiplos_rostos',
            'mensagem': 'A captura deve conter apenas um rosto.',
        }, status=400)

    encoding_atual = encodings_capturados[0]
    alunos_autorizados = rota_ativa.veiculo.alunos_autorizados.filter(is_aprovado=True)
    aluno_reconhecido = None
    for aluno in alunos_autorizados:
        if not aluno.dados_faciais:
            continue
        try:
            dados_brutos = json.loads(aluno.dados_faciais) if isinstance(aluno.dados_faciais, str) else aluno.dados_faciais
            conhecido_encoding = np.asarray(dados_brutos, dtype=float)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if conhecido_encoding.shape != (128,):
            continue
        if face_recognition.compare_faces([conhecido_encoding], encoding_atual, tolerance=0.5)[0]:
            aluno_reconhecido = aluno
            break

    # Serializa eventos concorrentes para não registrar dois embarques no mesmo instante.
    with transaction.atomic():
        processar_rotas_sem_gps(motorista_id=request.user.motorista.pk)
        rota_ativa = Rota.objects.select_for_update().filter(
            pk=rota_ativa.pk, motorista=request.user.motorista,
            ativa=True, interrompida=False,
        ).select_related('veiculo').first()
        if not rota_ativa:
            return JsonResponse({'status': 'erro', 'mensagem': 'A rota foi encerrada durante a captura.'}, status=409)

        if aluno_reconhecido and not rota_ativa.veiculo.alunos_autorizados.filter(
            pk=aluno_reconhecido.pk, is_aprovado=True,
        ).exists():
            aluno_reconhecido = None

        if not aluno_reconhecido:
            Evento.objects.create(rota=rota_ativa, tipo='desconhecido', autorizado=False)
            return JsonResponse({'status': 'desconhecido'})

        ultimo_evento = Evento.objects.filter(
            rota=rota_ativa, aluno=aluno_reconhecido,
        ).order_by('-data_hora', '-id').first()
        if ultimo_evento and (timezone.now() - ultimo_evento.data_hora).total_seconds() < 10:
            return JsonResponse({
                'status': 'carencia', 'aluno': aluno_reconhecido.nome,
                'mensagem': 'Aguarde alguns segundos antes de registrar outro evento.',
            })

        tipo_evento = 'embarque' if not ultimo_evento or ultimo_evento.tipo == 'desembarque' else 'desembarque'
        Evento.objects.create(
            rota=rota_ativa, aluno=aluno_reconhecido, tipo=tipo_evento, autorizado=True,
        )
        return JsonResponse({'status': 'sucesso', 'tipo': tipo_evento, 'aluno': aluno_reconhecido.nome})

@login_required(login_url='login')
def simulador_catraca(request):
    if not hasattr(request.user, 'motorista') or not request.user.is_aprovado:
        messages.error(request, 'Apenas motoristas aprovados podem operar a câmera.')
        return redirect('home')
    processar_rotas_sem_gps(motorista_id=request.user.motorista.pk)
    if not Rota.objects.filter(
        motorista=request.user.motorista, ativa=True, interrompida=False,
    ).exists():
        messages.error(request, 'Inicie uma rota antes de ativar a câmera.')
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

    processar_rotas_sem_gps()

    rotas = Rota.objects.select_related('veiculo', 'motorista', 'motorista__usuario').exclude(veiculo__isnull=True)
    if is_responsavel and not is_admin:
        rotas = rotas.filter(eventos__aluno__responsavel=usuario.responsavel).distinct()
    rotas = list(rotas.order_by('-ativa', '-inicio'))
    route_id = request.GET.get('rota')
    rota = next((item for item in rotas if str(item.id) == str(route_id)), None) if route_id else (rotas[0] if rotas else None)
    if rota is None:
        return JsonResponse({'rotas': [], 'rota': None})

    pontos = list(Localizacao.objects.filter(rota=rota).order_by('timestamp'))
    eventos_qs = Evento.objects.filter(rota=rota).select_related('aluno').exclude(tipo='desconhecido')
    if is_responsavel and not is_admin:
        eventos_qs = eventos_qs.filter(aluno__responsavel=usuario.responsavel)
    eventos = list(eventos_qs.order_by('data_hora'))

    def ponto_proximo_do_evento(evento):
        if not pontos:
            return None
        ponto = min(pontos, key=lambda item: abs((item.timestamp - evento.data_hora).total_seconds()))
        # Não atribui ao evento uma posição antiga se o GPS estava sem sinal.
        if abs((ponto.timestamp - evento.data_hora).total_seconds()) > 180:
            return None
        return ponto

    alertas_json = []
    if is_admin:
        desconhecidos = Evento.objects.filter(rota=rota, tipo='desconhecido').order_by('data_hora')
        for evento in desconhecidos:
            ponto = ponto_proximo_do_evento(evento)
            alertas_json.append({
                'hora': timezone.localtime(evento.data_hora).strftime('%H:%M:%S'),
                'latitude': float(ponto.latitude) if ponto else None,
                'longitude': float(ponto.longitude) if ponto else None,
            })

    def distancia_metros(a, b):
        raio = 6371000
        lat1, lat2 = radians(float(a.latitude)), radians(float(b.latitude))
        dlat = lat2 - lat1
        dlon = radians(float(b.longitude) - float(a.longitude))
        valor = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 2 * raio * atan2(sqrt(valor), sqrt(1 - valor))

    paradas = []
    grupo = []
    for ponto in pontos:
        if grupo and distancia_metros(grupo[-1], ponto) > 40:
            if len(grupo) > 1 and (grupo[-1].timestamp - grupo[0].timestamp).total_seconds() >= 120:
                paradas.append({'latitude': float(grupo[0].latitude), 'longitude': float(grupo[0].longitude),
                                'inicio': timezone.localtime(grupo[0].timestamp).strftime('%H:%M'),
                                'fim': timezone.localtime(grupo[-1].timestamp).strftime('%H:%M'),
                                'duracao_minutos': round((grupo[-1].timestamp - grupo[0].timestamp).total_seconds() / 60)})
            grupo = []
        grupo.append(ponto)
    if len(grupo) > 1 and (grupo[-1].timestamp - grupo[0].timestamp).total_seconds() >= 120:
        paradas.append({'latitude': float(grupo[0].latitude), 'longitude': float(grupo[0].longitude),
                        'inicio': timezone.localtime(grupo[0].timestamp).strftime('%H:%M'),
                        'fim': timezone.localtime(grupo[-1].timestamp).strftime('%H:%M'),
                        'duracao_minutos': round((grupo[-1].timestamp - grupo[0].timestamp).total_seconds() / 60)})

    eventos_json = []
    status_por_aluno = {}
    for evento in eventos:
        ponto = ponto_proximo_do_evento(evento)
        eventos_json.append({
            'aluno': evento.aluno.nome, 'tipo': evento.get_tipo_display(),
            'hora': timezone.localtime(evento.data_hora).strftime('%H:%M:%S'),
            'latitude': float(ponto.latitude) if ponto else None,
            'longitude': float(ponto.longitude) if ponto else None,
        })
        status_por_aluno[evento.aluno_id] = {
            'nome': evento.aluno.nome,
            'foto': evento.aluno.foto_perfil.url if evento.aluno.foto_perfil else '',
            'a_bordo': evento.tipo == 'embarque',
            'hora': timezone.localtime(evento.data_hora).strftime('%H:%M:%S'),
        }
    alunos_abordo = [aluno for aluno in status_por_aluno.values() if aluno['a_bordo']]

    agora = timezone.now()
    estado_gps = obter_estado_gps(rota, pontos[-1] if pontos else None, agora)

    def rotulo_rota(item):
        if item.interrompida:
            if item.ativa:
                estado = 'Interrompida · revisão pendente'
            elif item.resolvida_por_id:
                estado = 'Interrompida · revisão concluída'
            else:
                estado = 'Interrompida · encerrada automaticamente'
        elif item.ativa:
            estado = 'Em andamento' if obter_estado_gps(item, agora=agora) == 'atualizado' else 'Sem sinal'
        else:
            estado = 'Concluída'
        inicio = timezone.localtime(item.inicio).strftime('%d/%m/%Y %H:%M') if item.inicio else 'Data não informada'
        return {'id': item.id, 'label': f'{item.veiculo.placa} · {inicio} · {estado}'}

    return JsonResponse({
        'rotas': [rotulo_rota(item) for item in rotas],
        'rota': {
            'id': rota.id,
            'ativa': rota.ativa,
            'interrompida': rota.interrompida,
            'gps_status': estado_gps,
            'ultima_atualizacao': timezone.localtime(pontos[-1].timestamp).strftime('%d/%m/%Y %H:%M:%S') if pontos else None,
            'veiculo': str(rota.veiculo),
            'motorista': rota.motorista.usuario.first_name if rota.motorista else 'Não informado',
        },
        'trajeto': [{'latitude': float(p.latitude), 'longitude': float(p.longitude)} for p in pontos],
        'eventos': eventos_json, 'paradas': paradas, 'alertas': alertas_json,
        'alunos_abordo': alunos_abordo,
        'posicao_atual': ({
            'latitude': float(pontos[-1].latitude),
            'longitude': float(pontos[-1].longitude),
            'atualizado_em': timezone.localtime(pontos[-1].timestamp).strftime('%H:%M:%S'),
        } if pontos and rota.ativa and not rota.interrompida and estado_gps == 'atualizado' else None),
    })

@login_required(login_url='login')
def tela_mapa_unificado(request):
    if not (hasattr(request.user, 'instituicao') or hasattr(request.user, 'responsavel') or request.user.is_superuser):
        messages.error(request, 'Acesso permitido apenas à instituição e aos responsáveis.')
        return redirect('home')
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
    alunos = Aluno.objects.filter(is_aprovado=True).select_related('responsavel__usuario')

    if request.method == 'POST':
        modelo = request.POST.get('modelo', '').strip()
        capacidade = request.POST.get('capacidade')
        placa = request.POST.get('placa', '').strip().upper()
        cor = request.POST.get('cor', '').strip()
        foto = request.FILES.get('foto')
        motoristas_ids = request.POST.getlist('motoristas') # Pega a lista de IDs dos checkboxes
        alunos_ids = request.POST.getlist('alunos')

        if not all((modelo, capacidade, placa, cor)):
            messages.error(request, 'Preencha todos os campos obrigatórios do veículo.')
            return render(request, 'transporte/form_veiculo.html', {
                'veiculo': veiculo, 'motoristas': motoristas, 'alunos': alunos,
            })
        if len(modelo) > 100 or len(cor) > 30 or len(placa) > 10:
            messages.error(request, 'Modelo, cor ou placa excede o limite de caracteres permitido.')
            return render(request, 'transporte/form_veiculo.html', {
                'veiculo': veiculo, 'motoristas': motoristas, 'alunos': alunos,
            })
        try:
            capacidade = int(capacidade)
            if capacidade < 1:
                raise ValueError
        except (TypeError, ValueError):
            messages.error(request, 'A capacidade deve ser um número maior que zero.')
            return render(request, 'transporte/form_veiculo.html', {
                'veiculo': veiculo, 'motoristas': motoristas, 'alunos': alunos,
            })

        placa_em_uso = Veiculo.objects.filter(placa=placa)
        if veiculo:
            placa_em_uso = placa_em_uso.exclude(pk=veiculo.pk)
        if placa_em_uso.exists():
            messages.error(request, 'Já existe um veículo cadastrado com esta placa.')
            return render(request, 'transporte/form_veiculo.html', {
                'veiculo': veiculo, 'motoristas': motoristas, 'alunos': alunos,
            })

        if foto:
            if foto.size > 5 * 1024 * 1024:
                messages.error(request, 'A foto deve ter até 5 MB.')
                return render(request, 'transporte/form_veiculo.html', {
                    'veiculo': veiculo, 'motoristas': motoristas, 'alunos': alunos,
                })
            imagem_valida = True
            try:
                foto.seek(0)
                imagem = Image.open(foto)
                imagem.verify()
                imagem_valida = imagem_valida and imagem.format in {'JPEG', 'PNG', 'WEBP'}
                foto.seek(0)
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                imagem_valida = False
                foto.seek(0)
            if not imagem_valida:
                messages.error(request, 'A foto deve ser JPEG, PNG ou WebP válida e ter até 5 MB.')
                return render(request, 'transporte/form_veiculo.html', {
                    'veiculo': veiculo, 'motoristas': motoristas, 'alunos': alunos,
                })

        try:
            with transaction.atomic():
                if not veiculo:
                    veiculo = Veiculo.objects.create(modelo=modelo, capacidade=capacidade, placa=placa, cor=cor)
                else:
                    veiculo.modelo = modelo
                    veiculo.capacidade = capacidade
                    veiculo.placa = placa
                    veiculo.cor = cor
                    veiculo.save()

                if foto:
                    veiculo.foto = foto
                    veiculo.save(update_fields=['foto'])

                veiculo.motoristas_autorizados.set(motoristas.filter(id__in=motoristas_ids))
                veiculo.alunos_autorizados.set(alunos.filter(id__in=alunos_ids))
        except Exception:
            messages.error(request, 'Não foi possível salvar o veículo. Verifique os dados e tente novamente.')
            return render(request, 'transporte/form_veiculo.html', {
                'veiculo': veiculo, 'motoristas': motoristas, 'alunos': alunos,
            })

        messages.success(request, 'Veículo e vínculos salvos com sucesso.')

        return redirect('painel_veiculos')

    return render(request, 'transporte/form_veiculo.html', {'veiculo': veiculo, 'motoristas': motoristas, 'alunos': alunos})

@login_required(login_url='login')
def deletar_veiculo(request, id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')
    veiculo = get_object_or_404(Veiculo, id=id)
    if Rota.objects.filter(veiculo=veiculo).exists():
        messages.error(request, 'Não é possível excluir um veículo associado ao histórico de rotas.')
        return redirect('painel_veiculos')
    veiculo.delete()
    messages.error(request, 'Veículo removido do sistema.')
    return redirect('painel_veiculos')
