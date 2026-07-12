from datetime import date as date_cls, datetime, time, timedelta

from django.conf import settings
from django.utils import timezone

from doctors.models import WorkingHours

from .models import Appointment

SLOT_MINUTES = 30

# Bonus requirement: don't offer a slot starting within this many minutes of now.
MIN_LEAD_TIME_MINUTES = getattr(settings, "MIN_BOOKING_LEAD_MINUTES", 60)


def _generate_grid_slots(start_time: time, end_time: time) -> list[dict]:
    """Generate fixed 30-minute slots from start_time to end_time.
    Any remainder under SLOT_MINUTES is simply not offered — no special-casing needed."""
    slots = []
    current = datetime.combine(date_cls.today(), start_time)
    end = datetime.combine(date_cls.today(), end_time)
    step = timedelta(minutes=SLOT_MINUTES)

    while current + step <= end:
        slots.append({
            "start_time": current.time(),
            "end_time": (current + step).time(),
        })
        current += step

    return slots


def get_available_slots(doctor, target_date: date_cls) -> list[dict]:
    """Return all free 30-minute slots for a doctor on a given date.

    Availability = all generated grid slots for that weekday
                   minus any slot with an active ("booked") appointment
                   minus any slot that's already in the past / within the lead-time buffer.
    """
    weekday = target_date.weekday()  # Monday=0 ... Sunday=6, matches WorkingHours.Weekday

    try:
        hours = WorkingHours.objects.get(doctor=doctor, weekday=weekday)
    except WorkingHours.DoesNotExist:
        return []  # doctor is off this day

    all_slots = _generate_grid_slots(hours.start_time, hours.end_time)

    taken_times = set(
        Appointment.objects.filter(
            doctor=doctor, date=target_date, status=Appointment.Status.BOOKED,
        ).values_list("start_time", flat=True)
    )

    available = [slot for slot in all_slots if slot["start_time"] not in taken_times]

    # Exclude past/near-future slots only when the target date is today.
    now = timezone.now()
    if target_date == now.date():
        cutoff = (now + timedelta(minutes=MIN_LEAD_TIME_MINUTES)).time()
        available = [slot for slot in available if slot["start_time"] >= cutoff]

    return available