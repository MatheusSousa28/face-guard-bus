from django.urls import path
from . import views

urlpatterns = [
    path('iniciar-rota/', views.iniciar_rota, name='iniciar_rota'),
    path('finalizar_rota/', views.finalizar_rota, name='finalizar_rota'),
    path('api/gps/', views.receber_localizacao, name='api_gps'),
    path('api/posicao/<int:veiculo_id>/', views.api_posicao_onibus, name='api_posicao_onibus'),
    path('monitoramento-geral/', views.monitoramento_instituicao, name='monitoramento_geral'),
    path('api/frota/', views.api_todas_posicoes, name='api_frota'),
]