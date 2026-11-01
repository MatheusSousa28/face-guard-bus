from django.urls import path
from . import views

urlpatterns = [
    path('iniciar-rota/', views.iniciar_rota, name='iniciar_rota'),
    path('finalizar_rota/', views.finalizar_rota, name='finalizar_rota'),
    path('api/gps/', views.receber_localizacao, name='api_gps'),
    
    path('mapa-unificado/', views.tela_mapa_unificado, name='mapa_unificado'),
    
    path('api/reconhecimento/', views.api_reconhecimento, name='api_reconhecimento'),
    path('catraca/', views.simulador_catraca, name='simulador_catraca'),
    path('api/mapa-unificado/', views.api_frota_mapa_unificada, name='api_mapa_unificado'),
    path('painel/veiculos/', views.painel_veiculos, name='painel_veiculos'),
    path('painel/veiculos/novo/', views.gerenciar_veiculo, name='novo_veiculo'),
    path('painel/veiculos/editar/<int:id>/', views.gerenciar_veiculo, name='editar_veiculo'),
    path('painel/veiculos/deletar/<int:id>/', views.deletar_veiculo, name='deletar_veiculo'),
]