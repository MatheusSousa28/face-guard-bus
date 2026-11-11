from django.urls import path
from . import views

urlpatterns = [
    path('login/', view=views.login_view, name='login'),
    path('home/', view=views.painel_home, name='home'),
    path('perfil/editar/', views.editar_perfil, name='editar_perfil'),
    path('perfil/alterar-senha/', views.alterar_senha_propria, name='alterar_senha_propria'),
    path('cadastro/', view=views.cadastro_responsavel, name='cadastro'),
    path('painel/aprovacoes/', views.painel_instituicao_aprovacoes, name='painel_aprovacoes'),
    path('painel/aprovar/<str:tipo>/<int:obj_id>/', views.aprovar_cadastro, name='aprovar_cadastro'),
    path('painel/reprovar/<str:tipo>/<int:obj_id>/', views.reprovar_cadastro, name='reprovar_cadastro'),
    path('painel/usuarios/', views.painel_usuarios_ativos, name='painel_usuarios'),
    path('painel/motoristas/novo/', views.cadastrar_motorista, name='cadastrar_motorista'),
    path('painel/usuarios/deletar/<str:tipo>/<int:obj_id>/', views.deletar_usuario, name='deletar_usuario'),
    path('painel/auditoria/api/', views.api_auditoria, name='api_auditoria'),
    path('painel/usuarios/api/<str:tipo>/', views.api_usuarios, name='api_usuarios'),
    path('painel/usuarios/api/<str:tipo>/<int:obj_id>/senha/', views.api_redefinir_senha_usuario, name='api_redefinir_senha_usuario'),
    path('painel/usuarios/api/<str:tipo>/<int:obj_id>/', views.api_usuarios, name='api_usuario_detalhe'),
]
