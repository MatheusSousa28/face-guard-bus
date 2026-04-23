from django.contrib import admin
from .models import Evento

class EventoAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'aluno', 'rota', 'data_hora', 'autorizado')
    list_filter = ('tipo', 'autorizado', 'data_hora')
    search_fields = ('aluno__nome',)

admin.site.register(Evento, EventoAdmin)