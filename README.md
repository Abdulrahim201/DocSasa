# DocSasa

An online appointment booking system for patients and doctors, built with Django and Django REST Framework.

DocSasa lets patients see real-time availability for a set of doctors and book a slot directly, with no double-booking. The system currently supports up to **5 doctors**, but is designed so that limit can be raised with minimal changes as demand grows.

---

## Table of Contents
- [Overview](#overview)
- [System Design](#system-design)
- [Core Concepts](#core-concepts)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [System Architecture](#system-architecture)
- [Data Model](#data-model)
- [Booking Flow](#booking-flow)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Scalability Notes](#scalability-notes)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Patients often struggle to know when a doctor is actually free, and phone-based booking is slow and error-prone. DocSasa solves this by exposing each doctor's working hours as discrete, bookable **30-minute slots**. Patients pick a doctor and a date, see only the slots that are genuinely open, and book instantly. Once a slot is taken, it disappears from availability for everyone else. Patients can also cancel a booking, which releases the slot back into the pool.

## System Design

This section documents the reasoning behind the core design decisions — what was chosen, why, and what was deliberately left out of v1.

### Actors

- **Patient** — books, cancels, or reschedules their own appointments.
- **Receptionist** — books, cancels, or reschedules on behalf of a patient. In practice, many patients (particularly elderly patients) prefer a human to handle booking for them, so the receptionist is a first-class actor rather than an admin-only afterthought.
- **Doctor** — a largely passive actor in v1. Doctors define their own working hours and view their schedule/appointments, but do not book, cancel, or reschedule appointments themselves.

Patients and receptionists are both represented as a single `User` model (see [Key Decisions](#key-decisions), #6) — the system does not gate the booking endpoints by role.

### Key Decisions

1. **Slots are fixed-grid, not flexible.** A slot is the smallest bookable unit (30 minutes), generated starting at a doctor's `work_start` and stepping forward in fixed 30-minute increments until `work_end` is reached. A patient can only book on one of these fixed marks — not an arbitrary 30-minute window anywhere in the day. If a doctor's working hours don't divide evenly into 30-minute blocks (e.g. a 15-minute remainder at the end), that leftover time is simply never offered as a bookable slot — no special-casing required, the slot-generation loop naturally stops once fewer than 30 minutes remain.

2. **Doctors have per-weekday working hours, not one fixed daily schedule.** Doctors can have shorter hours on some days and be off entirely on others, so working hours live in a separate `WorkingHours` model (one row per doctor per weekday) rather than as fixed fields on `Doctor`. A weekday with no `WorkingHours` row is treated as a day off. v1 supports one contiguous working block per day; split shifts (e.g. a lunch-hour gap) are deferred (see [Deferred to Future Iterations](#deferred-to-future-iterations)).

3. **Times are stored as naive local time — no UTC conversion.** The clinic is a single physical location, so every patient, receptionist, and doctor shares the same timezone. Converting to and from UTC would add complexity with no real benefit here, so appointment times are stored and compared as local time directly.

4. **Concurrency is guarded at the database level, with a clean error path on top.** Two patients can hit "book" on the same doctor/slot within milliseconds of each other, so the correctness guarantee cannot live in application logic alone (a "check, then insert" pattern is not atomic — both requests can pass the check before either inserts). The design uses two layers:
   - A **`UniqueConstraint` on `(doctor, date, start_time)`**, scoped to active (non-cancelled) appointments. This is the actual source of truth — even under a bug elsewhere in the code, the database physically refuses a second insert for the same slot.
   - **`select_for_update()` inside `transaction.atomic()`** during the availability check. This doesn't add correctness (the constraint already guarantees that) — it makes the *losing* request fail gracefully with a clean "slot no longer available" error instead of surfacing a raw `IntegrityError`.

5. **A doctor's working hours can change without disturbing existing bookings.** If a doctor's hours are edited after appointments already exist, those appointments are **grandfathered** — they are not auto-cancelled or auto-moved. The new hours only affect future slot generation. As a lightweight safeguard, the system flags any existing appointment that now falls outside the updated hours so a receptionist can review and resolve it manually, rather than the system silently reassigning patients.

6. **A single `User` model, with no role-based restriction on the booking endpoints.** Patients and receptionists are both `User`s; there is no admin/staff permission tier distinguishing what a patient can do versus what a receptionist can do at the API level — either can book, cancel, or reschedule any appointment. This is a deliberate scope decision, not an oversight: the system isn't yet integrated with a clinic's real staff-permissions layer (e.g. an HMIS), so building a full role hierarchy now would be premature. Identity is still required on every request (the system isn't anonymous), because `booked_by` / `cancelled_by` are recorded on the appointment for the audit log.

7. **Rescheduling is an atomic "validate-then-swap," not a simple field update.** The requested new slot is validated using the *exact same rules as a fresh booking* (within working hours, not in the past, not already taken). Only once the new slot passes that validation does the system free the original slot and move the appointment onto the new date/time — both steps happen inside a single database transaction. If the new slot fails validation, the original booking is left completely untouched, so a patient can never end up losing their original slot without successfully gaining a new one.

### Deferred to Future Iterations

These were identified during design but intentionally left out of v1 to keep the core booking guarantees simple and correct within scope:

- **Automatic conflict resolution** when a doctor's hours change (e.g. auto-rescheduling or queuing affected patients). Flagging for manual review was chosen instead — it avoids the complexity of consent handling, ordering rules, and race conditions between an automatic rebook and a patient's own manual booking.
- **Split working shifts** (e.g. a doctor working 09:00–12:00 and 14:00–17:00 with a lunch gap) — v1 supports a single contiguous block per weekday.
- **`DoctorTimeOff`** — a model allowing a doctor to block off a single day or a date range (e.g. vacation), which would suppress slot generation for those dates:
  ```
  DoctorTimeOff
  - doctor (FK → Doctor)
  - start_date
  - end_date
  - reason (optional)
  ```
- **Role-based permissions** distinguishing patients from receptionists at the API layer, and integration with an external clinic HMIS.

## Core Concepts

- **Doctor working hours** — Each doctor has per-weekday working hours (they can differ by day, or be off entirely on some days). These hours generate the universe of possible slots for that doctor. Doctors are a largely passive actor: they set their hours and view their schedule, but don't book on their own behalf.
- **30-minute slots** — Working hours are divided into fixed 30-minute blocks, anchored to each day's start time. A slot is the smallest unit of booking.
- **Availability** — For a given doctor and date, availability = all generated slots minus any slot that already has an active (non-cancelled) appointment.
- **Booking** — A patient or a receptionist (on the patient's behalf) reserves exactly one free slot. The system enforces that a slot can only be booked once at a time to prevent race conditions (e.g. two requests booking simultaneously).
- **Cancellation** — Cancelling an appointment requires a reason, marks it inactive, and immediately frees the slot for rebooking, while preserving a record in the audit log/history.

## Features

- 🗓️ **Slot-based booking** — Patients (or a receptionist on their behalf) see only real, free 30-minute slots per doctor per day.
- 🚫 **No double-booking** — Database-level uniqueness constraints, backed by row locking, prevent two requests from booking the same slot.
- ❌ **Cancellations with a reason** — Cancelling requires a reason and frees the slot; cancelling an already-cancelled appointment returns an error.
- 🔁 **Rescheduling** — Move an appointment to a new slot, validated exactly like a fresh booking, without losing its history.
- 🕓 **Appointment history & audit logs** — Every booking, cancellation, and reschedule is tracked with who performed it, for accountability.
- 📧 **Email notifications** — Confirmation, cancellation, and reschedule emails.
- 🔌 **REST API** — Full API access via Django REST Framework for integration with a frontend (web/mobile) client.

## Tech Stack

| Layer            | Technology                     |
|-------------------|--------------------------------|
| Backend           | Django, Django REST Framework  |
| Database          | PostgreSQL                     |
| Notifications     | Django email backend (SMTP)    |
| Version Control   | Git                             |

## System Architecture

At a high level:

```
Patient (client / frontend)
        │
        ▼
   REST API (DRF)
        │
        ▼
  Django application layer
   ├── Doctors & Working Hours
   ├── Slot generation logic
   ├── Appointment booking/cancellation
   └── Audit logging
        │
        ▼
   PostgreSQL database
```

Slots are not necessarily stored as pre-created rows for all time — they can be **computed on the fly** from a doctor's working hours and compared against existing appointments for that day. This keeps the system lightweight while doctor count and date ranges grow. See [Scalability Notes](#scalability-notes) for details.

## Data Model

A simplified view of the core entities:

**Doctor**
- `id`
- `name`
- `specialty`

**WorkingHours**
- `id`
- `doctor` (FK → Doctor)
- `weekday` (0=Monday … 6=Sunday; no row for a weekday = doctor is off that day)
- `start_time`
- `end_time`

**User** *(shared by patients and receptionists — no role-based permission tier in v1)*
- `id`
- `name`
- `email` / `phone`
- `role` (`patient` / `receptionist` — for labeling/display only, not permission gating)

**Appointment**
- `id`
- `doctor` (FK → Doctor)
- `patient` (FK → User)
- `date`
- `start_time`
- `end_time` (derived: `start_time + 30 minutes`)
- `status` (`booked`, `cancelled`, `completed`)
- `cancellation_reason` (nullable — set when `status='cancelled'`)
- `booked_by` (FK → User — the patient themself, or the receptionist who booked on their behalf)
- `cancelled_by` (FK → User, nullable)
- `created_at`, `updated_at`

**AuditLog**
- `id`
- `appointment` (FK → Appointment)
- `action` (`created`, `cancelled`, `rescheduled`, `updated`)
- `performed_by` (FK → User)
- `timestamp`

> A `UniqueConstraint` on `(doctor, date, start_time)`, scoped to active (`booked`) appointments, is what guarantees a slot can't be double-booked — see [System Design → Key Decisions, #4](#key-decisions).

## Booking Flow

1. Patient (or a receptionist on their behalf) selects a **doctor**.
2. Patient/receptionist selects a **date**.
3. System generates all 30-minute slots from that doctor's working hours for that date, then removes any slot with an existing active appointment, along with any slot in the past or within a minimum lead time before the appointment (see [Roadmap](#roadmap) — bonus).
4. Patient/receptionist picks an available slot and confirms.
5. System attempts to create the appointment; the database-level uniqueness constraint ensures that if two requests race for the same slot, only one succeeds (see [System Design → Key Decisions, #4](#key-decisions)).
6. On success: appointment is saved with `booked_by` recorded, an audit log entry is created, and confirmation emails are sent.
7. To cancel: patient or receptionist cancels the appointment **and must supply a reason**; status is updated to `cancelled`, `cancelled_by` and `cancellation_reason` are recorded, an audit log entry is created, the slot becomes available again, and a cancellation email is sent. Attempting to cancel an already-cancelled appointment returns an error rather than silently succeeding.
8. To reschedule: patient or receptionist requests a new date/slot for an existing appointment. The new slot goes through the **exact same validation as a fresh booking** — it must be a valid slot within the doctor's working hours, not in the past, and not already have an active appointment. If valid, the system frees the **original slot** (making it immediately available to others) and moves the appointment to the new date/`start_time`/`end_time`, keeping the same appointment `id` and history. The change is logged as a `rescheduled` action and an update email is sent. If the new slot is unavailable or invalid, or the appointment is already cancelled, the request is rejected and the original booking is left untouched.

## Getting Started

### Prerequisites
- Python 3.x
- PostgreSQL
- [uv](https://docs.astral.sh/uv/) (used for virtual environment and dependency management)

### Installation

```bash
# Clone the repository
git clone https://github.com/Abdulrahim201/DocSasa.git
cd docsasa

# Create the virtual environment and install dependencies
uv sync

# Activate the virtual environment
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Configure environment variables
cp .env.example .env
# edit .env with your DB credentials, email settings, secret key, etc.

# Run migrations
uv run manage.py migrate

# Create a superuser (for admin/dashboard access)
uv run manage.py createsuperuser

# Start the development server
uv run manage.py runserver
```

> Commands are also runnable without activating the venv by prefixing with `uv run` (e.g. `uv run manage.py migrate`), which is the pattern used above.

### Environment Variables

Real secrets live in a local `.env` file, which is **git-ignored** and never committed (see `.gitignore`). Only `.env.example` — a template with variable names and no real values — is tracked in the repository. To configure your local environment: `cp .env.example .env`, then fill in real values.

| Variable            | Description                              |
|---------------------|-------------------------------------------|
| `SECRET_KEY`        | Django secret key                         |
| `DEBUG`             | `True`/`False`                            |
| `DATABASE_URL`      | PostgreSQL connection string              |
| `EMAIL_HOST`        | SMTP host for notifications               |
| `EMAIL_HOST_USER`   | SMTP username                             |
| `EMAIL_HOST_PASSWORD` | SMTP password                           |
| `MAX_DOCTORS`       | Current cap on number of doctors (default: 5) |

## API Reference

> Base URL: `/api/v1/`

**Required (per assessment spec):**

| Method | Endpoint                                       | Description                                                                 |
|--------|--------------------------------------------------|-------------------------------------------------------------------------------|
| POST   | `/appointments`                                | Book a slot. Validates it falls within the doctor's working hours, isn't in the past, and isn't already taken. |
| GET    | `/doctors/{id}/availability?date=YYYY-MM-DD`   | Return all available 30-minute slots for a doctor on a given date.           |
| PATCH  | `/appointments/{id}/cancel`                    | Cancel an appointment with a required `reason`. Errors if already cancelled. |
| PATCH  | `/appointments/{id}/reschedule`                | Move an appointment to a new slot, validated as a fresh booking. Errors if already cancelled. |

**Bonus (per assessment spec):**

| Method | Endpoint                          | Description                                                        |
|--------|-------------------------------------|----------------------------------------------------------------------|
| GET    | `/patients/{id}/appointments`     | Upcoming appointments for a patient, sorted by date.                |
| —      | *(validation rule)*                | Bookings are rejected if the slot starts within 1 hour of now.       |

**Additional (not required, added for completeness):**

| Method | Endpoint                                  | Description                                     |
|--------|--------------------------------------------|---------------------------------------------------|
| GET    | `/doctors/`                               | List all doctors                                   |
| GET    | `/appointments/`                          | List appointments for the current user            |
| GET    | `/appointments/{id}/`                     | Retrieve a single appointment                      |
| GET    | `/appointments/history/`                  | Appointment history / audit trail                  |
| GET    | `/dashboard/stats/`                       | Appointment statistics (booked/cancelled/etc.)     |

*(Adjust endpoint names/paths to match the actual `urls.py` once finalized.)*

## Scalability Notes

The project intentionally starts small (5 doctors) but is structured to grow:

- **Doctor limit** — The cap of 5 is a configuration value, not a hard architectural limit. Raising it is a matter of updating configuration/validation rather than redesigning the booking logic.
- **On-the-fly slot generation** — Because slots are derived from working hours rather than pre-populated for every future day, storage doesn't grow linearly with time; it grows with actual bookings.
- **Database-level integrity** — Uniqueness constraints (rather than application-only checks) prevent race conditions as concurrent traffic increases.
- **Stateless API layer** — The DRF layer can be horizontally scaled behind a load balancer since booking integrity is enforced at the database, not in server memory.
- **Indexing** — Indexes on `(doctor, date)` and `(doctor, date, start_time)` keep availability lookups fast as appointment volume grows.
- **Future path** — Introducing background workers (e.g. Celery) for email notifications, and caching (e.g. Redis) for frequently-requested availability, are natural next steps as load increases.

## Roadmap

**Bonus items from the assessment spec:**
- [ ] `GET /patients/{id}/appointments` — upcoming appointments for a patient, sorted by date
- [ ] Reject bookings that start within 1 hour of now

**Deferred design decisions (see [System Design → Deferred to Future Iterations](#deferred-to-future-iterations)):**
- [ ] `DoctorTimeOff` — let a doctor block off a day or date range
- [ ] Split working shifts within a single day (e.g. a lunch-hour gap)
- [ ] Automatic conflict resolution when a doctor's hours change (currently: grandfather + flag for manual review)
- [ ] Role-based permissions distinguishing patients from receptionists at the API layer

**Other possible extensions:**
- [ ] Doctor-side dashboard for managing their own schedule
- [ ] Rate limiting on the booking endpoint

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes
4. Push to the branch and open a Pull Request

## License

MIT