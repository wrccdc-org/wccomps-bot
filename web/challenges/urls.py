from django.urls import path

from challenges import views

app_name = "challenges"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("check-in/", views.toggle_checkin, name="toggle_checkin"),
    path("check-in/<int:user_id>/", views.admin_toggle_checkin, name="admin_toggle_checkin"),
]
