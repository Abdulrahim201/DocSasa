from django.urls import path

from .views import (
    DoctorAvailabilityView,
    DoctorDetailView,
    DoctorListCreateView,
    DoctorWorkingHoursView,
)

urlpatterns = [
    path("doctors/", DoctorListCreateView.as_view(), name="doctor-list-create"),
     path("doctors/<int:pk>/", DoctorDetailView.as_view(), name="doctor-detail"),
    path("doctors/<int:pk>/availability/", DoctorAvailabilityView.as_view(), name="doctor-availability"),
    path("doctors/<int:pk>/working-hours/", DoctorWorkingHoursView.as_view(), name="doctor-working-hours"),
]