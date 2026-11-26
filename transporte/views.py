import json
from datetime import timedelta
from django.conf import settings
from django.shortcuts import redirect, render, get_object_or_404
from django.http import HttpResponseNotAllowed, JsonResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from .models import Rota, Localizacao, Veiculo
from .services import (
    contar_alunos_a_bordo,
    obter_estado_gps,
    processar_rotas_sem_gps,
)
from usuarios.models import Motorista, CORES_AVATAR
from usuarios.monitoramento import obter_contexto_monitoramento
from alunos.models import Aluno
from django.contrib import messages
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Subquery
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
    if not observacao or len(observacao) > 500:
        messages.error(request, 'Informe uma observação de até 500 caracteres para registrar a revisão da rota.')
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
        rota.responsaveis_notificados_revisao = False
        rota.save(update_fields=[
            'ativa', 'fim', 'resolvida_por', 'resolvida_em', 'observacao_resolucao',
            'responsaveis_notificados_revisao',
        ])

    messages.success(request, 'A rota interrompida foi encerrada após revisão.')
    return redirect('home')


@login_required(login_url='login')
def confirmar_ciencia_rota_encerrada(request, rota_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not (hasattr(request.user, 'instituicao') or request.user.is_superuser):
        messages.error(request, 'Apenas a instituição pode confirmar ciência de uma rota encerrada.')
        return redirect('home')
    if request.POST.get('confirmacao_ciencia') != 'on':
        messages.error(request, 'Marque a confirmação de ciência para ocultar este aviso.')
        return redirect('home')

    with transaction.atomic():
        rota = Rota.objects.select_for_update().filter(
            pk=rota_id,
            ativa=False,
            interrompida=True,
            resolvida_por__isnull=True,
            instituicao_ciente_encerramento=False,
        ).first()
        if not rota:
            messages.error(request, 'Esta rota não possui um aviso pendente de ciência.')
            return redirect('home')
        rota.instituicao_ciente_encerramento = True
        rota.save(update_fields=['instituicao_ciente_encerramento'])

    messages.success(request, 'Ciência registrada; o aviso da rota foi dispensado.')
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
        
    if cache.add('transporte:monitoramento:processar-rotas', True, timeout=20):
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
    alunos_autorizados = rota_ativa.veiculo.alunos_autorizados.filter(is_aprovado=True, deleted_at__isnull=True)
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
            pk=aluno_reconhecido.pk, is_aprovado=True, deleted_at__isnull=True,
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

    if cache.add('transporte:monitoramento:processar-rotas', True, timeout=20):
        processar_rotas_sem_gps()

    rotas = Rota.objects.select_related(
        'veiculo', 'motorista', 'motorista__usuario',
    )
    if is_responsavel and not is_admin:
        rotas = rotas.filter(
            Q(veiculo__alunos_autorizados__responsavel=usuario.responsavel)
            | Exists(Evento.objects.filter(
                rota_id=OuterRef('pk'),
                aluno__responsavel=usuario.responsavel,
                autorizado=True,
            )),
        ).distinct()
    contexto = request.GET.get('contexto', 'ativas')
    termo = request.GET.get('q', '').strip()[:100]
    estado = request.GET.get('situacao', '').strip()[:40]
    aluno_id = request.GET.get('aluno', '').strip()[:20]
    motorista_id = request.GET.get('motorista', '').strip()[:20]
    veiculo_id = request.GET.get('veiculo', '').strip()[:20]
    if aluno_id.isdigit():
        aluno_rota = Q(veiculo__alunos_autorizados__id=aluno_id) | Exists(
            Evento.objects.filter(rota_id=OuterRef('pk'), aluno_id=aluno_id, autorizado=True)
        )
        rotas = rotas.filter(aluno_rota)
    if motorista_id.isdigit() and (is_admin or not is_responsavel):
        rotas = rotas.filter(motorista_id=motorista_id)
    if veiculo_id.isdigit() and (is_admin or not is_responsavel):
        rotas = rotas.filter(veiculo_id=veiculo_id)
    data_inicio = request.GET.get('data_inicio', '').strip()[:10]
    data_fim = request.GET.get('data_fim', '').strip()[:10]

    agora = timezone.now()
    resumo = {}
    somente_lista = request.GET.get('somente_lista') == '1' and contexto != 'historico'
    total_ativas = 0
    pagina = 1
    paginas_ativas = 1
    ultima_localizacao_qs = Localizacao.objects.filter(
        rota_id=OuterRef('pk'),
    ).order_by('-timestamp', '-pk')
    if contexto == 'historico':
        rotas = rotas.filter(ativa=False)
        if data_inicio:
            rotas = rotas.filter(inicio__date__gte=data_inicio)
        if data_fim:
            rotas = rotas.filter(inicio__date__lte=data_fim)
        if estado == 'interrompida':
            rotas = rotas.filter(interrompida=True)
        elif estado == 'concluida':
            rotas = rotas.filter(interrompida=False)
        if termo:
            busca = (
                Q(veiculo__placa__icontains=termo)
                | Q(veiculo__modelo__icontains=termo)
                | Q(motorista__usuario__first_name__icontains=termo)
                | Q(motorista__usuario__last_name__icontains=termo)
            )
            if termo.isdigit():
                busca |= Q(pk=int(termo))
            rotas = rotas.filter(busca)
        rotas_filtradas = rotas
        total_historico = rotas_filtradas.count()
        resumo['concluidas'] = rotas_filtradas.filter(interrompida=False).count()
        resumo['interrompidas'] = rotas_filtradas.filter(interrompida=True).count()
        resumo['embarques'] = Evento.objects.filter(
            rota__in=rotas_filtradas, tipo='embarque', autorizado=True,
        ).count()
        resumo['desembarques'] = Evento.objects.filter(
            rota__in=rotas_filtradas, tipo='desembarque', autorizado=True,
        ).count()
        try:
            pagina = max(1, int(request.GET.get('pagina', '1')))
        except (TypeError, ValueError):
            pagina = 1
        rotas = list(rotas.order_by('-inicio', '-pk')[(pagina - 1) * 5:pagina * 5])
    else:
        rotas = rotas.filter(ativa=True)
        if estado == 'andamento':
            rotas = rotas.filter(interrompida=False)
        elif estado == 'interrompida':
            rotas = rotas.filter(interrompida=True)
        if termo:
            busca = (
                Q(veiculo__placa__icontains=termo)
                | Q(veiculo__modelo__icontains=termo)
                | Q(motorista__usuario__first_name__icontains=termo)
                | Q(motorista__usuario__last_name__icontains=termo)
            )
            if termo.isdigit():
                busca |= Q(pk=int(termo))
            rotas = rotas.filter(busca)
        rotas = rotas.annotate(
            _ultima_gps_timestamp=Subquery(ultima_localizacao_qs.values('timestamp')[:1]),
        )
        if estado == 'sem_sinal':
            limite_sinal = agora - timedelta(seconds=90)
            rotas = rotas.filter(
                interrompida=False,
            ).filter(
                Q(_ultima_gps_timestamp__isnull=True) | Q(_ultima_gps_timestamp__lt=limite_sinal)
            )
        rotas_filtradas = rotas
        total_ativas = rotas_filtradas.count()
        if not somente_lista:
            resumo['rotas_em_andamento'] = rotas_filtradas.filter(interrompida=False).count()
            resumo['rotas_interrompidas'] = rotas_filtradas.filter(interrompida=True).count()
            resumo['rotas_sem_sinal'] = rotas_filtradas.filter(
                interrompida=False,
            ).filter(
                Q(_ultima_gps_timestamp__isnull=True)
                | Q(_ultima_gps_timestamp__lt=agora - timedelta(seconds=90))
            ).count()
            resumo['onibus_em_circulacao'] = rotas_filtradas.filter(
                interrompida=False,
                _ultima_gps_timestamp__gte=agora - timedelta(seconds=90),
            ).count()
        try:
            pagina = max(1, int(request.GET.get('pagina', '1')))
        except (TypeError, ValueError):
            pagina = 1
        paginas_ativas = max(1, (total_ativas + 4) // 5)
        pagina = min(pagina, paginas_ativas)
        if not somente_lista:
            resumo['embarques'] = Evento.objects.filter(
                rota__in=rotas_filtradas, tipo='embarque', autorizado=True,
            ).count()
            resumo['desembarques'] = Evento.objects.filter(
                rota__in=rotas_filtradas, tipo='desembarque', autorizado=True,
            ).count()
            ultimo_evento_aluno = Evento.objects.filter(
                rota_id=OuterRef('rota_id'), aluno_id=OuterRef('aluno_id'),
                aluno__isnull=False,
            ).order_by('-data_hora', '-pk')
            eventos_a_bordo = Evento.objects.filter(
                rota__in=rotas_filtradas, aluno__isnull=False,
            ).filter(pk=Subquery(ultimo_evento_aluno.values('pk')[:1]), tipo='embarque').count()
            resumo['alunos_abordo'] = eventos_a_bordo
        total_historico = 0
        rotas = list(
            rotas_filtradas.order_by('-inicio', '-pk')[
                (pagina - 1) * 5:pagina * 5
            ]
        )

    route_id = request.GET.get('rota')
    rota = None
    if route_id:
        rota = Rota.objects.select_related(
            'veiculo', 'motorista', 'motorista__usuario',
        ).filter(pk=route_id)
        if is_responsavel and not is_admin:
            rota = rota.filter(
                Q(veiculo__alunos_autorizados__responsavel=usuario.responsavel)
                | Exists(Evento.objects.filter(
                    rota_id=OuterRef('pk'),
                    aluno__responsavel=usuario.responsavel,
                    autorizado=True,
                )),
            )
        rota = rota.first()
    if route_id and rota is None:
        return JsonResponse({'error': 'Rota não encontrada.'}, status=404)

    def url_imagem(campo):
        try:
            return campo.url if campo else ''
        except (ValueError, AttributeError):
            return ''

    def rotulo_rota(item):
        if item.interrompida:
            if item.ativa:
                estado = 'Interrompida · revisão pendente'
            elif item.resolvida_por_id:
                estado = 'Interrompida · revisão concluída'
            else:
                estado = 'Interrompida · encerrada automaticamente'
        elif item.ativa:
            atualizado = bool(
                item._ultima_gps_timestamp
                and agora - item._ultima_gps_timestamp <= timedelta(seconds=90)
            )
            estado = 'Em andamento' if atualizado else 'Sem sinal'
        else:
            estado = 'Concluída'
        inicio = timezone.localtime(item.inicio).strftime('%d/%m/%Y %H:%M') if item.inicio else 'Data não informada'
        placa = item.veiculo.placa if item.veiculo_id else 'Veículo não informado'
        motorista = (
            f"{item.motorista.usuario.first_name} {item.motorista.usuario.last_name}".strip()
            if item.motorista_id else 'Não informado'
        )
        gps_status = 'historica'
        if item.ativa:
            gps_status = 'interrompida' if item.interrompida else (
                'atualizado' if item._ultima_gps_timestamp
                and agora - item._ultima_gps_timestamp <= timedelta(seconds=90)
                else 'sem_sinal'
            )
        return {
            'id': item.id, 'label': f'{placa} · {inicio} · {estado}',
            'placa': placa, 'motorista': motorista,
            'capacidade': item.veiculo.capacidade if item.veiculo_id else 0,
            'inicio': inicio, 'ativa': item.ativa, 'interrompida': item.interrompida,
            'gps_status': gps_status,
            'veiculo_foto': url_imagem(item.veiculo.foto) if item.veiculo_id else '',
            'motorista_foto': url_imagem(item.motorista.foto_perfil) if item.motorista_id else '',
        }

    rotas_json = [rotulo_rota(item) for item in rotas]
    if somente_lista:
        return JsonResponse({
            'rotas': rotas_json,
            'posicoes_ativas': [],
            'contexto': contexto,
            'total': total_ativas,
            'resumo': {},
            'pagina': pagina,
            'paginas': paginas_ativas,
        })
    posicoes_ativas = []
    if rota and rota.ativa and rota.veiculo_id:
        ultima_posicao = rota.coordenadas.order_by('-timestamp', '-pk').first()
        if ultima_posicao:
            posicoes_ativas.append({
                'rota_id': rota.id,
                'latitude': float(ultima_posicao.latitude),
                'longitude': float(ultima_posicao.longitude),
                'veiculo': str(rota.veiculo),
                'placa': rota.veiculo.placa,
                'cor': rota.veiculo.cor_avatar,
                'veiculo_foto': url_imagem(rota.veiculo.foto),
                'motorista_foto': url_imagem(rota.motorista.foto_perfil) if rota.motorista_id else '',
                'motorista': (
                    f"{rota.motorista.usuario.first_name} {rota.motorista.usuario.last_name}".strip()
                    if rota.motorista_id else 'Não informado'
                ),
                'gps_status': 'interrompida' if rota.interrompida else (
                    'atualizado' if agora - ultima_posicao.timestamp <= timedelta(seconds=90)
                    else 'sem_sinal'
                ),
                'atualizado_em': timezone.localtime(ultima_posicao.timestamp).strftime('%H:%M:%S'),
            })

    if rota is None:
        return JsonResponse({
            'rotas': rotas_json,
            'posicoes_ativas': posicoes_ativas,
            'contexto': contexto,
            'total': total_historico if contexto == 'historico' else total_ativas,
            'resumo': resumo,
            'pagina': pagina,
            'paginas': ((total_historico + 4) // 5) if contexto == 'historico' else paginas_ativas,
            'rota': None,
            'trajeto': [],
            'eventos': [],
            'paradas': [],
            'alertas': [],
            'alunos_abordo': [],
            'posicao_atual': None,
        })

    pontos = list(Localizacao.objects.filter(rota=rota).order_by('timestamp'))
    eventos_qs = Evento.objects.filter(
        rota=rota, autorizado=True,
    ).select_related('aluno').exclude(tipo='desconhecido')
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
    embarques = 0
    desembarques = 0
    for evento in eventos:
        if evento.tipo == 'embarque':
            embarques += 1
        elif evento.tipo == 'desembarque':
            desembarques += 1
        ponto = ponto_proximo_do_evento(evento)
        eventos_json.append({
            'aluno': evento.aluno.nome if evento.aluno else 'Aluno não informado',
            'aluno_id': evento.aluno_id, 'tipo': evento.get_tipo_display(),
            'hora': timezone.localtime(evento.data_hora).strftime('%d/%m/%Y %H:%M:%S'),
            'timestamp': evento.data_hora.isoformat(),
            'foto': url_imagem(evento.aluno.foto_perfil) if evento.aluno_id else '',
            'latitude': float(ponto.latitude) if ponto else None,
            'longitude': float(ponto.longitude) if ponto else None,
        })
        if evento.aluno_id is None:
            continue
        status_atual = status_por_aluno.setdefault(evento.aluno_id, {
            'id': evento.aluno_id,
            'nome': evento.aluno.nome,
            'foto': url_imagem(evento.aluno.foto_perfil),
            'a_bordo': False,
            'hora': '',
            'hora_embarque': None,
            'hora_desembarque': None,
            'embarcou': False,
        })
        hora_evento = timezone.localtime(evento.data_hora).strftime('%H:%M:%S')
        if evento.tipo == 'embarque':
            status_atual['hora_embarque'] = hora_evento
            status_atual['embarcou'] = True
        elif evento.tipo == 'desembarque':
            status_atual['hora_desembarque'] = hora_evento
        status_atual['a_bordo'] = evento.tipo == 'embarque'
        status_atual['hora'] = hora_evento
        status_atual['tipo'] = evento.get_tipo_display()
    alunos_historico = [aluno for aluno in status_por_aluno.values() if aluno['embarcou']]
    alunos_abordo = [aluno for aluno in alunos_historico if aluno['a_bordo']]

    estado_gps = obter_estado_gps(rota, pontos[-1] if pontos else None, agora)

    return JsonResponse({
        'rotas': rotas_json,
        'posicoes_ativas': posicoes_ativas,
        'contexto': contexto,
        'total': total_historico if contexto == 'historico' else total_ativas,
        'resumo': resumo,
        'pagina': pagina,
        'paginas': ((total_historico + 4) // 5) if contexto == 'historico' else paginas_ativas,
        'rota': {
            'id': rota.id,
            'ativa': rota.ativa,
            'interrompida': rota.interrompida,
            'inicio': timezone.localtime(rota.inicio).strftime('%d/%m/%Y %H:%M:%S') if rota.inicio else None,
            'fim': timezone.localtime(rota.fim).strftime('%d/%m/%Y %H:%M:%S') if rota.fim else None,
            'duracao_segundos': max(0, int(((rota.fim or agora) - rota.inicio).total_seconds())) if rota.inicio else None,
            'gps_status': estado_gps,
            'ultima_atualizacao': timezone.localtime(pontos[-1].timestamp).strftime('%d/%m/%Y %H:%M:%S') if pontos else None,
            'veiculo': str(rota.veiculo) if rota.veiculo_id else 'Não informado',
            'veiculo_foto': url_imagem(rota.veiculo.foto) if rota.veiculo_id else '',
            'motorista': (
                f"{rota.motorista.usuario.first_name} {rota.motorista.usuario.last_name}".strip()
                if rota.motorista_id else 'Não informado'
            ),
            'motorista_foto': url_imagem(rota.motorista.foto_perfil) if rota.motorista_id else '',
            'placa': rota.veiculo.placa if rota.veiculo else 'Não informado',
            'capacidade': rota.veiculo.capacidade if rota.veiculo_id else 0,
            'embarques': embarques,
            'desembarques': desembarques,
            'total_alunos': len(alunos_historico),
            'alunos_historico': alunos_historico,
            'ocorrencias': sum(1 for evento in Evento.objects.filter(rota=rota, tipo='desconhecido')),
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
def api_posicao_rota(request, rota_id):
    usuario = request.user
    is_admin = hasattr(usuario, 'instituicao') or usuario.is_superuser
    is_responsavel = hasattr(usuario, 'responsavel')
    if not (is_admin or is_responsavel):
        return JsonResponse({'error': 'Acesso negado'}, status=403)

    rota_qs = Rota.objects.filter(pk=rota_id)
    if is_responsavel and not is_admin:
        rota_qs = rota_qs.filter(
            Q(veiculo__alunos_autorizados__responsavel=usuario.responsavel)
            | Exists(Evento.objects.filter(
                rota_id=OuterRef('pk'),
                aluno__responsavel=usuario.responsavel,
                autorizado=True,
            )),
        ).distinct()
    rota = rota_qs.first()
    if rota is None:
        return JsonResponse({'error': 'Rota não encontrada.'}, status=404)

    ultima_posicao = rota.coordenadas.order_by('-timestamp', '-pk').first()
    gps_recente = bool(
        ultima_posicao
        and timezone.now() - ultima_posicao.timestamp <= timedelta(seconds=90)
    )
    return JsonResponse({
        'rota_id': rota.pk,
        'ativa': rota.ativa,
        'interrompida': rota.interrompida,
        'gps_status': 'atualizado' if gps_recente else 'sem_sinal',
        'posicao': {
            'latitude': float(ultima_posicao.latitude),
            'longitude': float(ultima_posicao.longitude),
            'atualizado_em': timezone.localtime(ultima_posicao.timestamp).strftime('%H:%M:%S'),
        } if ultima_posicao else None,
    })


@login_required(login_url='login')
def api_filtros_monitoramento(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    usuario = request.user
    is_admin = hasattr(usuario, 'instituicao') or usuario.is_superuser
    is_responsavel = hasattr(usuario, 'responsavel')
    tipo = request.GET.get('tipo', '')
    termo = request.GET.get('q', '').strip()[:80]
    if not termo:
        return JsonResponse({'results': []})

    if tipo == 'aluno' and (is_admin or is_responsavel):
        alunos = Aluno.objects.filter(deleted_at__isnull=True)
        if is_responsavel and not is_admin:
            alunos = alunos.filter(responsavel=usuario.responsavel)
        else:
            alunos = alunos.filter(is_aprovado=True)
        resultados = [
            {'id': aluno.pk, 'label': aluno.nome}
            for aluno in alunos.filter(nome__icontains=termo).order_by('nome', 'pk')[:25]
        ]
    elif tipo == 'motorista' and is_admin:
        motoristas = Motorista.objects.filter(
            deleted_at__isnull=True, usuario__is_active=True, usuario__is_aprovado=True,
        ).filter(
            Q(usuario__first_name__icontains=termo)
            | Q(usuario__last_name__icontains=termo)
        ).select_related('usuario').order_by('usuario__first_name', 'usuario__last_name', 'pk')[:25]
        resultados = [{'id': pessoa.pk, 'label': pessoa.usuario.get_full_name()} for pessoa in motoristas]
    elif tipo == 'veiculo' and is_admin:
        veiculos = Veiculo.objects.filter(
            Q(modelo__icontains=termo) | Q(placa__icontains=termo)
        ).order_by('modelo', 'placa', 'pk')[:25]
        resultados = [{'id': veiculo.pk, 'label': f'{veiculo.modelo} · {veiculo.placa}'} for veiculo in veiculos]
    else:
        return JsonResponse({'error': 'Filtro indisponível para este perfil.'}, status=403)
    return JsonResponse({'results': resultados})


@login_required(login_url='login')
def tela_mapa_unificado(request):
    if not (hasattr(request.user, 'instituicao') or hasattr(request.user, 'responsavel') or request.user.is_superuser):
        messages.error(request, 'Acesso permitido apenas à instituição e aos responsáveis.')
        return redirect('home')
    contexto = {}
    if hasattr(request.user, 'instituicao') or request.user.is_superuser:
        contexto = obter_contexto_monitoramento()
    contexto['carto_api_key'] = settings.CARTO_API_KEY
    return render(request, 'transporte/mapa_unificado.html', contexto)

@login_required(login_url='login')
def painel_veiculos(request):
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')
    veiculos = Veiculo.objects.all()
    return render(request, 'transporte/painel_veiculos.html', {'veiculos': veiculos})


@login_required(login_url='login')
def api_alunos_para_veiculo(request):
    if not hasattr(request.user, 'instituicao'):
        return JsonResponse({'erro': 'Acesso permitido apenas à instituição.'}, status=403)
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    termo = request.GET.get('q', '').strip()[:100]
    qs = Aluno.objects.filter(is_aprovado=True, deleted_at__isnull=True).select_related(
        'responsavel__usuario'
    ).order_by('nome', 'pk')
    if termo:
        qs = qs.filter(Q(nome__icontains=termo)
                       | Q(responsavel__usuario__first_name__icontains=termo)
                       | Q(responsavel__usuario__last_name__icontains=termo))
    try:
        page_num = max(1, int(request.GET.get('page', '1')))
    except (TypeError, ValueError):
        page_num = 1
    start = (page_num - 1) * 25
    items = list(qs[start:start + 26])
    return JsonResponse({
        'results': [{'id': a.pk, 'nome': a.nome,
                     'responsavel': a.responsavel.usuario.get_full_name()}
                    for a in items[:25]],
        'has_more': len(items) > 25,
    })

@login_required(login_url='login')
def gerenciar_veiculo(request, id=None):
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')
    
    veiculo = get_object_or_404(Veiculo, id=id) if id else None
    motoristas = Motorista.objects.filter(usuario__is_aprovado=True, usuario__is_active=True, deleted_at__isnull=True)
    alunos_selecionados = ([{
        'id': aluno.pk, 'nome': aluno.nome,
        'responsavel': aluno.responsavel.usuario.get_full_name(),
    } for aluno in veiculo.alunos_autorizados.filter(
        is_aprovado=True, deleted_at__isnull=True
    ).select_related('responsavel__usuario')] if veiculo else [])
    avatar_colors = CORES_AVATAR

    if request.method == 'POST':
        modelo = request.POST.get('modelo', '').strip()
        capacidade = request.POST.get('capacidade')
        placa = request.POST.get('placa', '').strip().upper()
        cor = request.POST.get('cor', '').strip()
        foto = request.FILES.get('foto')
        remover_foto = request.POST.get('remover_foto') == '1'
        motoristas_ids = request.POST.getlist('motoristas') # Pega a lista de IDs dos checkboxes
        alunos_ids = request.POST.getlist('alunos')
        if alunos_ids:
            alunos_selecionados = [{
                'id': aluno.pk, 'nome': aluno.nome,
                'responsavel': aluno.responsavel.usuario.get_full_name(),
            } for aluno in Aluno.objects.filter(
                pk__in=alunos_ids, is_aprovado=True, deleted_at__isnull=True,
            ).select_related('responsavel__usuario')]

        if not all((modelo, capacidade, placa, cor)):
            messages.error(request, 'Preencha todos os campos obrigatórios do veículo.')
            return render(request, 'transporte/form_veiculo.html', {
                'veiculo': veiculo, 'motoristas': motoristas, 'alunos_selecionados': alunos_selecionados,
                'avatar_colors': avatar_colors,
            })
        if len(modelo) > 100 or len(cor) > 30 or len(placa) > 10:
            messages.error(request, 'Modelo, cor ou placa excede o limite de caracteres permitido.')
            return render(request, 'transporte/form_veiculo.html', {
                'veiculo': veiculo, 'motoristas': motoristas, 'alunos_selecionados': alunos_selecionados,
                'avatar_colors': avatar_colors,
            })
        try:
            capacidade = int(capacidade)
            if not 1 <= capacidade <= 100:
                raise ValueError
        except (TypeError, ValueError):
            messages.error(request, 'A capacidade deve estar entre 1 e 100 alunos.')
            return render(request, 'transporte/form_veiculo.html', {
                'veiculo': veiculo, 'motoristas': motoristas, 'alunos_selecionados': alunos_selecionados,
                'avatar_colors': avatar_colors,
            })

        placa_em_uso = Veiculo.objects.filter(placa=placa)
        if veiculo:
            placa_em_uso = placa_em_uso.exclude(pk=veiculo.pk)
        if placa_em_uso.exists():
            messages.error(request, 'Já existe um veículo cadastrado com esta placa.')
            return render(request, 'transporte/form_veiculo.html', {
                'veiculo': veiculo, 'motoristas': motoristas, 'alunos_selecionados': alunos_selecionados,
                'avatar_colors': avatar_colors,
            })

        if foto:
            if foto.size > 5 * 1024 * 1024:
                messages.error(request, 'A foto deve ter até 5 MB.')
                return render(request, 'transporte/form_veiculo.html', {
                    'veiculo': veiculo, 'motoristas': motoristas, 'alunos_selecionados': alunos_selecionados,
                    'avatar_colors': avatar_colors,
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
                    'veiculo': veiculo, 'motoristas': motoristas, 'alunos_selecionados': alunos_selecionados,
                    'avatar_colors': avatar_colors,
                })

        try:
            with transaction.atomic():
                if not veiculo:
                    cor_avatar = request.POST.get('cor_avatar')
                    if cor_avatar not in {cor for cor, _ in CORES_AVATAR}:
                        cor_avatar = CORES_AVATAR[0][0]
                    veiculo = Veiculo.objects.create(modelo=modelo, capacidade=capacidade, placa=placa, cor=cor, cor_avatar=cor_avatar)
                else:
                    veiculo.modelo = modelo
                    veiculo.capacidade = capacidade
                    veiculo.placa = placa
                    veiculo.cor = cor
                    cor_avatar = request.POST.get('cor_avatar')
                    if cor_avatar in {cor for cor, _ in CORES_AVATAR}:
                        veiculo.cor_avatar = cor_avatar
                    veiculo.save()

                if foto:
                    veiculo.foto = foto
                    veiculo.save(update_fields=['foto'])
                elif remover_foto and veiculo.foto:
                    foto_antiga = veiculo.foto
                    veiculo.foto = None
                    veiculo.save(update_fields=['foto'])
                    foto_antiga.delete(save=False)

                veiculo.motoristas_autorizados.set(motoristas.filter(id__in=motoristas_ids))
                veiculo.alunos_autorizados.set(Aluno.objects.filter(
                    id__in=alunos_ids, is_aprovado=True, deleted_at__isnull=True,
                ))
        except Exception:
            messages.error(request, 'Não foi possível salvar o veículo. Verifique os dados e tente novamente.')
            return render(request, 'transporte/form_veiculo.html', {
                'veiculo': veiculo, 'motoristas': motoristas, 'alunos_selecionados': alunos_selecionados,
                'avatar_colors': avatar_colors,
            })

        messages.success(request, 'Veículo e vínculos salvos com sucesso.')

        return redirect('painel_veiculos')

    return render(request, 'transporte/form_veiculo.html', {'veiculo': veiculo, 'motoristas': motoristas, 'alunos_selecionados': alunos_selecionados, 'avatar_colors': avatar_colors})

@login_required(login_url='login')
def deletar_veiculo(request, id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not hasattr(request.user, 'instituicao'):
        return redirect('home')
    veiculo = get_object_or_404(Veiculo, id=id)
    confirmacao = request.POST.get('confirmacao_numero', '')
    if confirmacao != str(veiculo.pk):
        messages.error(request, 'Número de confirmação incorreto. O veículo não foi excluído.')
        return redirect('painel_veiculos')
    if Rota.objects.filter(veiculo=veiculo).exists():
        messages.error(request, 'Não é possível excluir um veículo associado ao histórico de rotas.')
        return redirect('painel_veiculos')
    veiculo.delete()
    messages.error(request, 'Veículo removido do sistema.')
    return redirect('painel_veiculos')
