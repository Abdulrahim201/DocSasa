from django.contrib import admin

from .models import AuditLog, OTP, Appointment, Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone")
    search_fields = ("name", "email", "phone")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "doctor", "date", "start_time", "status")
    list_filter = ("status", "doctor", "date")
    search_fields = ("patient__name", "patient__email", "id")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("appointment", "action", "performed_by_user", "timestamp")
    list_filter = ("action",)
    readonly_fields = ("timestamp",)


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ("appointment", "purpose", "code", "is_used", "expires_at")
    list_filter = ("purpose", "is_used")
    readonly_fields = ("created_at", "expires_at")