import csv
from django.shortcuts import render
from django.conf import settings 
from django.http import JsonResponse

def list_pulses(request):
    pulses = []
    with open(settings.CSV_PATH, newline = "", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for l in reader:
            pulses.append(l)
    return JsonResponse({"pulses": pulses})

def pulses(request):
    return render(request, "index.html")

