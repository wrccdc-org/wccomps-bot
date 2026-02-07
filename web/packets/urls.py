"""URL configuration for packets app."""

from django.urls import path

from . import views

urlpatterns = [
    # Team member packet access
    path("", views.team_packets_list, name="team_packets_list"),
    path("download/<int:packet_id>/", views.download_packet, name="download_packet"),
    # GoldTeam operations
    path("ops/", views.ops_packets_list, name="ops_packets_list"),
    path("ops/upload/", views.ops_upload_packet, name="ops_upload_packet"),
    path("ops/<int:packet_id>/", views.ops_packet_detail, name="ops_packet_detail"),
    path(
        "ops/<int:packet_id>/distribute/",
        views.ops_distribute_packet,
        name="ops_distribute_packet",
    ),
    path(
        "ops/<int:packet_id>/cancel/",
        views.ops_cancel_packet,
        name="ops_cancel_packet",
    ),
    path(
        "ops/<int:packet_id>/reset/",
        views.ops_reset_packet,
        name="ops_reset_packet",
    ),
    path(
        "ops/<int:packet_id>/test-email/",
        views.ops_send_test_email,
        name="ops_send_test_email",
    ),
]
