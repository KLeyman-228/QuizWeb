from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from .models import Lobby


def index_view(request):
    return render(request, "index.html")

def lobby_view(request, code):
    lobby = get_object_or_404(Lobby, code=code.upper())
    return render(request, "lobby.html", {"code": lobby.code})

def host_view(request, code):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Доступ запрещён")
    lobby = get_object_or_404(Lobby, code=code.upper())
    return render(request, "host.html", {"code": lobby.code})

@csrf_exempt
@require_POST
def new_lobby_api(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Доступ запрещён")
    code = Lobby.generate_code()
    Lobby.objects.create(code=code)
    return JsonResponse({"code": code})
