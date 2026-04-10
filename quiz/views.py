from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from .models import Lobby


def index_view(request):
    return render(request, "index.html")

def lobby_view(request, code):
    return render(request, "lobby.html", {"code": code})

def host_view(request, code):
    return render(request, "host.html", {"code": code})

@csrf_exempt
@require_POST
def new_lobby_api(request):
    code = Lobby.generate_code()
    Lobby.objects.create(code=code)
    return JsonResponse({"code": code})