from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Instituicao, Responsavel, Motorista

#exibição de tabelas no painel admin

#cria uma classe para dizer como a tabela Usuario deve aparecer
class CustomUserAdmin(UserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'is_aprovado', 'is_staff')
    
    list_filter = ('is_aprovado', 'is_staff', 'is_superuser')

    fieldsets = UserAdmin.fieldsets + (
        ('Status de Aprovação Institucional', {'fields': ('is_aprovado',)}),
    )

#usando a configuração customizada
admin.site.register(Usuario, CustomUserAdmin)

admin.site.register(Responsavel)
admin.site.register(Instituicao)
admin.site.register(Motorista)