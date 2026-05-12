from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView
from usuarios import views as usuarios_views
from alunos import views as alunos_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(pattern_name='home'), name='raiz'),
    
    path('login/', usuarios_views.login_view, name='login'),
    path('home/', usuarios_views.painel_home, name='home'),
    path('cadastro/', usuarios_views.cadastro_responsavel, name='cadastro'),
    
    path('alunos/cadastrar/', alunos_views.cadastro_aluno, name='cadastro_aluno'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)