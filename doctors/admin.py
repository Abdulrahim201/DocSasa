from django.contrib import admin

from .models import Doctor, WorkingHours


class WorkingHoursInline(admin.TabularInline):
    model = WorkingHours
    extra = 1
    fields = ("weekday", "start_time", "end_time")


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ("name", "specialty", "id")
    search_fields = ("name", "specialty")
    inlines = [WorkingHoursInline]


@admin.register(WorkingHours)
class WorkingHoursAdmin(admin.ModelAdmin):
    list_display = ("doctor", "weekday_label", "start_time", "end_time")
    list_filter = ("weekday", "doctor")

    @admin.display(description="Weekday", ordering="weekday")
    def weekday_label(self, obj):
        return obj.get_weekday_display()