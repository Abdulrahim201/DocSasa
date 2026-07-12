from django.contrib import admin
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("doctors.urls")),
    path("api/v1/", include("appointments.urls")),
    path("api/v1/auth/login/", obtain_auth_token, name="api-login"),
]