from django.urls import path
from . import views

urlpatterns = [
    path("", views.health, name="health"),
    path("health", views.health, name="health-alt"),
    path("register", views.register, name="register"),
    path("login", views.login, name="login"),
    path("logout", views.logout, name="logout"),
    path("me", views.me, name="me"),
    path("me/data", views.delete_my_data, name="delete-my-data"),
    path("me/data/export", views.export_my_data, name="export-my-data"),
    path("datas", views.datas_collection, name="datas-collection"),
    path("datas/<int:user_id>", views.datas_by_user, name="datas-by-user"),
    path("statistics/<int:user_id>", views.statistics_by_user, name="statistics-by-user"),
    path("bracelets/pair", views.pair_bracelet, name="pair-bracelet"),
    path("bracelets/<int:user_id>", views.list_bracelets, name="list-bracelets"),
]