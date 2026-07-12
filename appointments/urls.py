from django.urls import path

from .views import (
    BookAppointmentView,
    CancelAppointmentView,
    RequestOTPView,
    RescheduleAppointmentView,
    PatientAppointmentsView,
)

urlpatterns = [
    path("appointments/", BookAppointmentView.as_view(), name="appointment-book"),
    path("appointments/<uuid:pk>/cancel/", CancelAppointmentView.as_view(), name="appointment-cancel"),
    path("appointments/<uuid:pk>/reschedule/", RescheduleAppointmentView.as_view(), name="appointment-reschedule"),
    path("appointments/<uuid:pk>/request-otp/", RequestOTPView.as_view(), name="appointment-request-otp"),
    path("patients/<int:pk>/appointments/", PatientAppointmentsView.as_view(), name="patient-appointments"),
]