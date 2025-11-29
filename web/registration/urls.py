"""URL patterns for registration app."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.register, name="registration_register"),
    path("review/", views.review_list, name="registration_review_list"),
    path("approve/<int:registration_id>/", views.approve_registration, name="registration_approve"),
    path("reject/<int:registration_id>/", views.reject_registration, name="registration_reject"),
]
