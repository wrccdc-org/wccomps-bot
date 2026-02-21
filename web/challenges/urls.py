from django.urls import path

from challenges import views

app_name = "challenges"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
]
