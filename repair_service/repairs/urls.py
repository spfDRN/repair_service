from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("services/", views.services_page, name="services"),
    path("about/", views.about, name="about"),
    path("contacts/", views.contacts, name="contacts"),
    path("track/", views.track, name="track"),
    path("track/<str:number>/", views.track_detail, name="track_detail"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", views.register, name="register"),
    path("after-login/", views.after_login, name="after_login"),
    path("cabinet/", views.dashboard, name="cabinet"),
    path("cabinet/orders/", views.order_list, name="cabinet_orders"),
    path("cabinet/orders/new/", views.order_new, name="cabinet_order_new"),
    path("cabinet/orders/<int:pk>/", views.order_detail, name="cabinet_order"),
    path("cabinet/devices/", views.devices, name="cabinet_devices"),
    path("cabinet/warranty/", views.warranty, name="cabinet_warranty"),
    path("cabinet/profile/", views.profile, name="cabinet_profile"),
    path("cabinet/password/", views.CabinetPasswordChangeView.as_view(), name="cabinet_password"),
    path("staff/orders/", views.staff_orders, name="staff_orders"),
    path("staff/orders/export/", views.staff_export, name="staff_export"),
    path("staff/orders/<int:pk>/diagnosis/", views.staff_order, name="staff_order"),
    path("staff/orders/<int:pk>/assign/", views.staff_assign, name="staff_assign"),
    path("staff/dashboard/", views.staff_dashboard, name="staff_dashboard"),
    path("api/orders/<int:pk>/status/", views.status_json, name="status_json"),
]