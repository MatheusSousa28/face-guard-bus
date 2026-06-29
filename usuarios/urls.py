from django.urls import path
from . import views

urlpatterns = [
    path('login/', view=views.login_view, name='login'),
    path('home/', view=views.painel_home, name='home'),
    path('cadastro/', view=views.cadastro_responsavel, name='cadastro'),
    path('painel/aprovacoes/', views.painel_instituicao_aprovacoes, name='painel_aprovacoes'),
    path('painel/aprovar/<str:tipo>/<int:obj_id>/', views.aprovar_cadastro, name='aprovar_cadastro'),
    path('painel/reprovar/<str:tipo>/<int:obj_id>/', views.reprovar_cadastro, name='reprovar_cadastro'),
]