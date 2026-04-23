from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Instituicao, Responsavel, Motorista

#exibição de tabelas no painel admin
admin.site.register(Usuario, UserAdmin)#tabela abstrata exibida de forma segura e organizada cm o useradmin
admin.site.register(Instituicao)
admin.site.register(Responsavel)
admin.site.register(Motorista)