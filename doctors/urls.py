from django.urls import path

from .views import DoctorAvailabilityView

urlpatterns = [
    path("doctors/<int:pk>/availability/", DoctorAvailabilityView.as_view(), name="doctor-availability"),
]