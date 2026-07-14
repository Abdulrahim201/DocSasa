from django.urls import path

from .views import (
    AppointmentListCreateView,
    CancelAppointmentView,
    RequestOTPView,
    RescheduleAppointmentView,
    PatientAppointmentsView,
    AppointmentDetailView
    
)

urlpatterns = [
    path("appointments/", AppointmentListCreateView.as_view(), name="appointment-list-create"),
    path("appointments/<uuid:pk>/", AppointmentDetailView.as_view(), name="appointment-detail"),
    path("appointments/<uuid:pk>/cancel/", CancelAppointmentView.as_view(), name="appointment-cancel"),
    path("appointments/<uuid:pk>/reschedule/", RescheduleAppointmentView.as_view(), name="appointment-reschedule"),
    path("appointments/<uuid:pk>/request-otp/", RequestOTPView.as_view(), name="appointment-request-otp"),
    path("patients/<int:pk>/appointments/", PatientAppointmentsView.as_view(), name="patient-appointments"),

]