from datetime import date as date_cls, datetime, time, timedelta
from django.conf import settings
from django.utils import timezone
from doctors.models import WorkingHours
from .models import Appointment, AuditLog, Patient
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from .models import Patient
from django.core.mail import send_mail
from .models import OTP


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
    now = timezone.now()

    # A date entirely in the past has no valid slots at all — no appointment
    # can ever be booked for a day that's already gone.
    if target_date < now.date():
        return []
    
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

class BookingError(Exception):
    """Base class for booking-related failures with a user-facing message."""


class SlotUnavailableError(BookingError):
    pass


class InvalidSlotError(BookingError):
    pass


def _validate_slot_request(doctor, target_date, start_time):
    """Validate a requested slot exactly like a fresh availability check —
    used by both book_appointment and reschedule_appointment."""
    available = get_available_slots(doctor, target_date)
    if not any(slot["start_time"] == start_time for slot in available):
        raise SlotUnavailableError(
            "This slot is not available. It may be outside working hours, "
            "in the past, or already booked."
        )
    # end_time is always start_time + SLOT_MINUTES, by definition of the fixed grid
    end_time = (
        datetime.combine(target_date, start_time) + timedelta(minutes=SLOT_MINUTES)
    ).time()
    return end_time


def book_appointment(*, doctor, date, start_time, patient_name, patient_email,
                      patient_phone="", booked_by_user=None):
    """Book a slot for a patient. Validates the slot exactly like a fresh
    availability check, then relies on the unique_active_slot DB constraint
    as the actual correctness guarantee under concurrent requests."""
    end_time = _validate_slot_request(doctor, date, start_time)

    patient, _ = Patient.objects.get_or_create(
        email=patient_email,
        defaults={"name": patient_name, "phone": patient_phone},
    )

    try:
        with transaction.atomic():
             # full_clean() intentionally skipped here — end_time is always derived
             # correctly by _validate_slot_request, so this call site is trusted.
            appointment = Appointment.objects.create(
                doctor=doctor,
                patient=patient,
                date=date,
                start_time=start_time,
                end_time=end_time,
                booked_by_user=booked_by_user,
            )
            AuditLog.objects.create(
                appointment=appointment,
                action=AuditLog.Action.CREATED,
                performed_by_user=booked_by_user,
            )
    except IntegrityError:
        # Someone else booked this exact slot between our availability check
        # and this insert — the DB constraint is the real source of truth here.
        raise SlotUnavailableError(
            "This slot was just booked by someone else. Please choose another."
        )
    manage_url = f"{settings.FRONTEND_BASE_URL}/appointments/{appointment.id}"
    send_mail(
        subject="Your DocSasa appointment is confirmed",
        message=(
            f"Your appointment with {doctor.name} on {date} at {start_time} is confirmed.\n\n"
            f"To view, reschedule, or cancel this appointment, visit:\n{manage_url}\n\n"
            f"Note: rescheduling or cancelling will require a one-time code sent to this email."
        ),
        from_email=None,
        recipient_list=[patient_email],
    )

    return appointment

def cancel_appointment(*, appointment_id, reason, performed_by_user=None):
    """Cancel an appointment. Rejects if already cancelled.
    select_for_update() locks the row for the duration of the transaction,
    protecting against a concurrent cancel/reschedule racing on the same appointment."""
    if not reason:
        raise BookingError("A cancellation reason is required.")

    with transaction.atomic():
        try:
            appointment = Appointment.objects.select_for_update().get(pk=appointment_id)
        except Appointment.DoesNotExist:
            raise BookingError("Appointment not found.")

        if appointment.status == Appointment.Status.CANCELLED:
            raise BookingError("This appointment is already cancelled.")

        appointment.status = Appointment.Status.CANCELLED
        appointment.cancellation_reason = reason
        appointment.cancelled_by_user = performed_by_user
        appointment.save(update_fields=[
            "status", "cancellation_reason", "cancelled_by_user", "updated_at",
        ])

        AuditLog.objects.create(
            appointment=appointment,
            action=AuditLog.Action.CANCELLED,
            performed_by_user=performed_by_user,
            notes=reason,
        )

    return appointment

def reschedule_appointment(*, appointment_id, new_date, new_start_time, performed_by_user=None):
    """Move an appointment to a new slot. The new slot is validated exactly
    like a fresh booking. The original slot is freed and the new slot is
    taken in a single UPDATE statement (same row, same transaction) — so
    there's no window where the appointment holds neither slot, and no
    window where it holds both."""

    with transaction.atomic():
        try:
            appointment = Appointment.objects.select_for_update().get(pk=appointment_id)
        except Appointment.DoesNotExist:
            raise BookingError("Appointment not found.")

        if appointment.status == Appointment.Status.CANCELLED:
            raise BookingError("Cannot reschedule a cancelled appointment.")

        if appointment.date == new_date and appointment.start_time == new_start_time:
            raise BookingError("This is already the appointment's current slot.")

        # Validated exactly like a fresh booking — same working-hours, past-time,
        # and already-taken checks as book_appointment(). This appointment's own
        # (old) slot doesn't interfere, since we're checking availability for the
        # *new* date/time, not the one this row currently occupies.
        new_end_time = _validate_slot_request(
            appointment.doctor, new_date, new_start_time
        )

        old_date, old_start_time = appointment.date, appointment.start_time

        appointment.date = new_date
        appointment.start_time = new_start_time
        appointment.end_time = new_end_time

        try:
            appointment.save(update_fields=["date", "start_time", "end_time", "updated_at"])
        except IntegrityError:
            # Someone else took the new slot between our validation and this save.
            # The transaction rolls back entirely — appointment keeps its original
            # slot, exactly as if the reschedule had never been attempted.
            raise SlotUnavailableError(
                "That slot was just taken by someone else. Please choose another."
            )

        AuditLog.objects.create(
            appointment=appointment,
            action=AuditLog.Action.RESCHEDULED,
            performed_by_user=performed_by_user,
            notes=f"Moved from {old_date} {old_start_time} to {new_date} {new_start_time}",
        )

    return appointment


def request_otp(appointment, purpose):
    """Generate and email a one-time code for a patient to verify a
    cancel/reschedule action on their own appointment, without logging in."""
    otp = OTP.objects.create(
        appointment=appointment,
        code=OTP.generate_code(),
        purpose=purpose,
    )
    send_mail(
        subject=f"Your DocSasa verification code",
        message=(
            f"Your one-time code to {purpose} your appointment is: {otp.code}\n"
            f"This code expires in 10 minutes and can only be used once."
        ),
        from_email=None,  # uses DEFAULT_FROM_EMAIL from settings
        recipient_list=[appointment.patient.email],
    )
    return otp


def verify_otp(appointment, purpose, code):
    """Check a submitted OTP code. Raises BookingError if invalid/expired/
    already used. Marks it used on success so it can't be replayed."""
    otp = (
        OTP.objects.filter(appointment=appointment, purpose=purpose, code=code, is_used=False)
        .order_by("-created_at")
        .first()
    )
    if not otp or not otp.is_valid():
        raise BookingError("Invalid or expired verification code.")

    otp.is_used = True
    otp.save(update_fields=["is_used"])