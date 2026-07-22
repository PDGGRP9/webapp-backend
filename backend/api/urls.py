from django.urls import path
from . import views

urlpatterns = [
    path("pulses/", views.list_pulses, name="pulses"),
    path("", views.pulses, name="main")
]