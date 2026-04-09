from django.contrib import admin
from .models import Lobby, Player, Question

# MODELS

admin.site.register(Lobby)
admin.site.register(Player)
admin.site.register(Question)