from django.urls import path

from challenges import views

app_name = "challenges"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("check-in/", views.toggle_checkin, name="toggle_checkin"),
    path("check-in/<int:user_id>/", views.admin_toggle_checkin, name="admin_toggle_checkin"),
    path("checks/", views.check_list, name="check_list"),
    path("checks/create/", views.check_create, name="check_create"),
    path("checks/<int:check_id>/", views.check_detail, name="check_detail"),
    path("checks/<int:check_id>/edit/", views.check_edit, name="check_edit"),
    path("checks/<int:check_id>/duplicate/", views.check_duplicate, name="check_duplicate"),
    path("checks/<int:check_id>/assign/", views.check_assign, name="check_assign"),
]
