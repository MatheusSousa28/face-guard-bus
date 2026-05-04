from django.urls import path
from . import views

urlpatterns = [
    path('login/', view=views.login_view, name='login'),
    path('home/', view=views.painel_home, name='home'),
    path('cadastro/', view=views.cadastro_responsavel, name='cadastro'),
]