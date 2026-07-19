# DocSasa

An online appointment booking system for patients and doctors, built with Django REST Framework on the backend and React on the frontend.

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
- [Frontend](#frontend)
- [Deployment](#deployment)
- [API Reference](#api-reference)
- [Testing](#testing)
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

- **Patient** — books, cancels, or reschedules their own appointments **without ever creating an account or logging in**. A patient is represented by a lightweight `Patient` record (name, email, phone) attached to their appointment — not a `User`.
- **Receptionist** — an authenticated `User` who books, cancels, or reschedules on behalf of a patient. In practice, many patients (particularly elderly patients) prefer a human to handle booking for them, so the receptionist is a first-class actor rather than an admin-only afterthought.
- **Doctor** — a largely passive actor in v1. Doctors define their own working hours and view their schedule/appointments, but do not book, cancel, or reschedule appointments themselves, and do not need a login for that (schedule setup can be done by a receptionist/admin via the admin site).

`User` in this system represents **staff only** (see [Key Decisions](#key-decisions), #6) — patients are never required to authenticate. Since a patient-initiated cancel/reschedule therefore has no login to rely on for verification, it's instead verified with a one-time email code (see #8, OTP verification).

### Key Decisions

1. **Slots are fixed-grid, not flexible.** A slot is the smallest bookable unit (30 minutes), generated starting at a doctor's `work_start` and stepping forward in fixed 30-minute increments until `work_end` is reached. A patient can only book on one of these fixed marks — not an arbitrary 30-minute window anywhere in the day. If a doctor's working hours don't divide evenly into 30-minute blocks (e.g. a 15-minute remainder at the end), that leftover time is simply never offered as a bookable slot — no special-casing required, the slot-generation loop naturally stops once fewer than 30 minutes remain.

2. **Doctors have per-weekday working hours, not one fixed daily schedule.** Doctors can have shorter hours on some days and be off entirely on others, so working hours live in a separate `WorkingHours` model (one row per doctor per weekday) rather than as fixed fields on `Doctor`. A weekday with no `WorkingHours` row is treated as a day off. v1 supports one contiguous working block per day; split shifts (e.g. a lunch-hour gap) are deferred (see [Deferred to Future Iterations](#deferred-to-future-iterations)).

3. **Times are stored as naive local time — no UTC conversion.** The clinic is a single physical location, so every patient, receptionist, and doctor shares the same timezone. Converting to and from UTC would add complexity with no real benefit here, so appointment times are stored and compared as local time directly.

4. **Concurrency is guarded at the database level, with a clean error path on top.** Two patients can hit "book" on the same doctor/slot within milliseconds of each other, so the correctness guarantee cannot live in application logic alone (a "check, then insert" pattern is not atomic — both requests can pass the check before either inserts). The design uses two layers:
   - A **`UniqueConstraint` on `(doctor, date, start_time)`**, scoped to active (non-cancelled) appointments. This is the actual source of truth — even under a bug elsewhere in the code, the database physically refuses a second insert for the same slot.
   - **`select_for_update()` inside `transaction.atomic()`** during the availability check. This doesn't add correctness (the constraint already guarantees that) — it makes the *losing* request fail gracefully with a clean "slot no longer available" error instead of surfacing a raw `IntegrityError`.

5. **A doctor's working hours can change without disturbing existing bookings.** If a doctor's hours are edited after appointments already exist, those appointments are **grandfathered** — they are not auto-cancelled or auto-moved. The new hours only affect future slot generation. As a lightweight safeguard, the system flags any existing appointment that now falls outside the updated hours so a receptionist can review and resolve it manually, rather than the system silently reassigning patients.

6. **`User` represents staff only — patients never authenticate.** Early in the design, both patients and receptionists were considered as one `User` model. This was revised: requiring every patient to create an account and log in undercuts the whole reason a receptionist exists as a fallback (elderly patients, in particular, often don't want to deal with an account at all). So `User` (Django's custom, auth-backed model) now represents receptionists/staff only, while patients are represented by a separate, login-free `Patient` record. There is still no role hierarchy *among* staff `User`s — any receptionist can act on any appointment — since the system isn't yet integrated with a clinic's real staff-permissions layer (e.g. an HMIS), so building a full role hierarchy now would be premature.

7. **Rescheduling is an atomic "validate-then-swap," not a simple field update.** The requested new slot is validated using the *exact same rules as a fresh booking* (within working hours, not in the past, not already taken). Only once the new slot passes that validation does the system update the appointment's date/time — freeing the original slot and taking the new one happen as the *same* database `UPDATE` statement, inside one transaction. If the new slot fails validation (including a last-moment `IntegrityError` if someone else grabbed it in the meantime), the whole transaction rolls back and the original booking is left completely untouched, so a patient can never end up losing their original slot without successfully gaining a new one.

8. **Appointment IDs are UUIDs, not sequential integers.** Since patients act on their own appointments without logging in (see #6), the appointment ID itself becomes part of the access control story — it's the thing that gets put in a link and clicked. A sequential integer ID would let someone enumerate or guess other patients' appointment IDs; a UUID makes that infeasible at negligible cost.

9. **Patient self-service (cancel/reschedule) is verified with a one-time email code, not a name check.** Since patients don't log in, *something* has to confirm the person acting on an appointment is actually who they claim to be. A name-based check was considered first, but names aren't unique or secret, so a short-lived, single-use 6-digit OTP emailed to the patient's address was chosen instead — it's a real (if lightweight) proof of access to the inbox tied to the appointment. Booking a *new* appointment doesn't require an OTP (low risk — it doesn't disrupt an existing appointment), but cancel/reschedule do. **Staff (`User`) requests are exempt from OTP** — their authenticated session plus the audit log (`cancelled_by_user` / `booked_by_user` / `AuditLog.performed_by_user`) already provides equivalent accountability, so requiring OTP for staff too would just be redundant friction. Phone/SMS-based OTP was considered and explicitly deferred (see [Deferred to Future Iterations](#deferred-to-future-iterations)) — email reuses infrastructure already needed for notifications, without pulling in a third-party SMS provider for v1.

10. **The confirmation email includes a direct manage-appointment link, not a UUID the patient has to remember.** Patients are never expected to memorize or type their appointment ID; the booking confirmation email links straight to a manage page for that appointment. The OTP requirement (#9) still applies when actually cancelling/rescheduling from that page — the link only grants *viewing* access, since a link can outlive its original context (forwarded, cached, a lost device), while the OTP is a fresh, action-specific check at the moment something is actually changed.

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
- **Phone/SMS-based OTP verification.** v1 verifies patient self-service actions (cancel/reschedule) by email OTP only. Phone number is still captured on `Patient` (useful for staff to call a patient directly), but isn't wired into any verification flow. SMS OTP would require integrating a third-party provider (e.g. Twilio, Africa's Talking) — deferred to v1.1+ once that added cost/complexity is worth it.
- **Rate limiting on OTP requests** — nothing currently stops repeated OTP requests for the same appointment; worth adding (e.g. max 3 per appointment per hour) before production use, to prevent inbox-spamming abuse.

- **Rescheduling confirmation** v1 does not send an email to the users once rescheduling is done from the staff, the assumption was that for a reschedule to happen the patient gives consent to make the changes according to their availability. However when the patient reschedule their appointments manually they recieve the rescheduling confirmation. 

## Core Concepts

- **Doctor working hours** — Each doctor has per-weekday working hours (they can differ by day, or be off entirely on some days). These hours generate the universe of possible slots for that doctor. Doctors are a largely passive actor: they set their hours and view their schedule, but don't book on their own behalf.
- **30-minute slots** — Working hours are divided into fixed 30-minute blocks, anchored to each day's start time. A slot is the smallest unit of booking.
- **Availability** — For a given doctor and date, availability = all generated slots minus any slot that already has an active (non-cancelled) appointment.
- **Booking** — A patient or a receptionist (on the patient's behalf) reserves exactly one free slot. The system enforces that a slot can only be booked once at a time to prevent race conditions (e.g. two requests booking simultaneously).
- **Cancellation** — Cancelling an appointment requires a reason, marks it inactive, and immediately frees the slot for rebooking, while preserving a record in the audit log/history.

## Features

- 🗓️ **Slot-based booking, no login required** — Patients see only real, free 30-minute slots per doctor per day and book directly, with no account needed. A receptionist can also book on a patient's behalf.
- 🚫 **No double-booking** — A database-level uniqueness constraint is the actual guarantee, backed by row locking for a clean error response when two requests race.
- 🔐 **OTP-verified self-service** — Patients cancel/reschedule their own appointment using a one-time code emailed to them; authenticated staff skip this since their session already provides accountability.
- ❌ **Cancellations with a reason** — Cancelling requires a reason and frees the slot; cancelling an already-cancelled appointment returns an error.
- 🔁 **Rescheduling** — Move an appointment to a new slot, validated exactly like a fresh booking, without losing its history.
- 🕓 **Appointment history & audit logs** — Every booking, cancellation, and reschedule is tracked with who performed it (or that it was self-service), for accountability.
- 📧 **Email notifications** — Confirmation (with a manage-appointment link), cancellation, reschedule, and OTP emails.
- 🔌 **REST API** — Full API access via Django REST Framework for integration with a frontend (web/mobile) client.

## Tech Stack

| Layer            | Technology                     |
|-------------------|--------------------------------|
| Backend           | Django, Django REST Framework  |
| Frontend          | React (Vite), React Router, Tailwind CSS |
| Database          | PostgreSQL                     |
| Auth              | DRF Token Authentication (staff only) |
| Notifications     | Django email backend (console in dev; SMTP-ready) |
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
   ├── services.py — slot generation, booking, cancel, reschedule (framework-agnostic business logic)
   ├── OTP verification (for patient self-service, no login)
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

**User** *(staff only — receptionists/admins; patients never get an account)*
- `id`
- `username`, `email`, `password` (inherited from Django's built-in auth user)
- `role` (`receptionist` / `admin` — for labeling/display only, not permission gating between staff)

**Patient** *(no login — identified by email; a link in the confirmation email, not a login, is how a patient finds their own appointment)*
- `id`
- `name`
- `email` (required — the only channel used for OTP verification in v1)
- `phone` (optional — informational only, e.g. for staff to call)

**Appointment**
- `id` (**UUID**, not a sequential integer — deliberately unguessable, since it's safe to put in a link a patient clicks without logging in)
- `doctor` (FK → Doctor)
- `patient` (FK → Patient)
- `date`
- `start_time`
- `end_time` (derived: `start_time + 30 minutes`)
- `status` (`booked`, `cancelled`, `completed`)
- `cancellation_reason` (nullable — set when `status='cancelled'`)
- `booked_by_user` (FK → User, **nullable** — null means the patient booked directly themself; set means a receptionist booked on their behalf)
- `cancelled_by_user` (FK → User, nullable — same meaning as above)
- `created_at`, `updated_at`

**AuditLog**
- `id`
- `appointment` (FK → Appointment)
- `action` (`created`, `cancelled`, `rescheduled`, `updated`)
- `performed_by_user` (FK → User, nullable — null means the patient acted directly, verified via OTP rather than a login)
- `notes`
- `timestamp`

**OTP** *(verifies a patient acting on their own appointment without a login — see [System Design → Key Decisions, #9](#key-decisions))*
- `id`
- `appointment` (FK → Appointment)
- `code` (6 digits)
- `purpose` (`cancel` / `reschedule` — a code for one purpose can't be reused for the other)
- `expires_at` (10-minute validity window)
- `is_used` (single-use)
- `created_at`

> A `UniqueConstraint` on `(doctor, date, start_time)`, scoped to active (`booked`) appointments, is what guarantees a slot can't be double-booked — see [System Design → Key Decisions, #4](#key-decisions).

## Booking Flow

1. Patient (no login required) or a receptionist (logged in) selects a **doctor**.
2. Patient/receptionist selects a **date**.
3. System generates all 30-minute slots from that doctor's working hours for that date, then removes any slot with an existing active appointment, along with any slot in the past or within a minimum lead time before the appointment (`MIN_BOOKING_LEAD_MINUTES`, default 60 — see [Roadmap](#roadmap) bonus item).
4. Patient/receptionist picks an available slot and confirms. Booking requires no OTP — it's low-risk since it doesn't disrupt an existing appointment.
5. System attempts to create the appointment; the database-level uniqueness constraint ensures that if two requests race for the same slot, only one succeeds (see [System Design → Key Decisions, #4](#key-decisions)).
6. On success: appointment is saved with `booked_by_user` set only if a receptionist made the booking (null if the patient booked directly), an audit log entry is created, and a confirmation email is sent to the patient — including a direct link to manage (cancel/reschedule) that specific appointment.
7. To cancel or reschedule as a **patient** (no login): the patient requests a one-time code, emailed to the address on the appointment, then submits it alongside the cancel/reschedule request. The code is single-use, purpose-specific (a `cancel` code can't be used to `reschedule`), and expires after 10 minutes.
8. To cancel or reschedule as a **receptionist** (logged in): no OTP is required — their authenticated session, combined with `cancelled_by_user`/`booked_by_user` and the audit log entry, already provides equivalent accountability.
9. **Cancelling** requires a reason; status is updated to `cancelled`, `cancellation_reason` (and `cancelled_by_user`, if staff-initiated) are recorded, an audit log entry is created, the slot becomes available again, and a cancellation email is sent. Attempting to cancel an already-cancelled appointment returns an error rather than silently succeeding.
10. **Rescheduling** validates the new slot with the **exact same rules as a fresh booking** — within the doctor's working hours, not in the past, not already taken. If valid, the appointment's date/`start_time`/`end_time` are updated in a single database statement inside one transaction — the original slot is freed and the new slot is taken atomically, so there's no window where the appointment holds neither slot or both. The change is logged as a `rescheduled` action and an update email is sent. If the new slot turns out to be unavailable (including a last-moment race), or the appointment is already cancelled, the request is rejected and the transaction rolls back — the original booking is left completely untouched.

## Getting Started

### Prerequisites
- Python 3.x
- [Docker](https://docs.docker.com/get-docker/) & Docker Compose (used to run PostgreSQL locally)
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

# Start PostgreSQL (Docker)
docker compose up -d

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
| `DATABASE_URL`      | PostgreSQL connection string (points at the Dockerized `db` service for local dev, e.g. `postgres://docsasa_user:docsasa_password@localhost:5432/docsasa`) |
| `EMAIL_BACKEND`     | Django email backend. Defaults to the **console backend** (`django.core.mail.backends.console.EmailBackend`), which prints emails to the terminal instead of sending them — no SMTP setup needed for local dev. Override to `django.core.mail.backends.smtp.EmailBackend` (with the vars below) for real delivery. |
| `EMAIL_HOST`        | SMTP host for notifications (only used if `EMAIL_BACKEND` is set to the SMTP backend) |
| `EMAIL_HOST_USER`   | SMTP username                             |
| `EMAIL_HOST_PASSWORD` | SMTP password                           |
| `MAX_DOCTORS`       | Current cap on number of doctors (default: 5) |
| `MIN_BOOKING_LEAD_MINUTES` | Minimum minutes before a slot's start time for it to be bookable (default: 60) |
| `FRONTEND_BASE_URL` | Base URL of the React app, used to build the manage-appointment link sent in confirmation emails (default: `http://localhost:5173`) |

## Frontend

A React (Vite) single-page app lives in `frontend/`, covering all three actors:

- **Patient booking** (`/`) — pick a doctor, date, and slot, enter contact details, and book. No login. Past dates are disabled in the date picker, and the backend independently rejects any past/too-soon slot regardless of what the UI allows.
- **Manage appointment** (`/appointments/:id`) — the page a patient reaches via the link in their confirmation email. Shows the appointment's current details and lets them cancel (with a reason) or reschedule, both gated behind a one-time email code requested from this same page.
- **Staff login** (`/staff/login`) — authenticates against the DRF token endpoint and stores the token in `localStorage`.
- **Staff dashboard** (`/staff/dashboard`) — lists all appointments with date/status filters. Requires a valid staff token; redirects to login otherwise. Each booked appointment has inline **Cancel** and **Reschedule** actions right in the row — no navigation away from the list, no OTP prompt (the receptionist's token is what authorizes the action; the backend's `request.user.is_authenticated` check is what waives the OTP requirement). This directly supports the common real-world case of a patient calling in to cancel or move their appointment over the phone.
- **Doctor management** (`/staff/doctors`) — add a doctor, and set their working hours either one weekday at a time or via an "Apply Mon–Fri" shortcut that upserts the same hours across all five weekdays in one action.

### Running the frontend

```bash
cd frontend
npm install
npm run dev
```

This starts the Vite dev server, typically at `http://localhost:5173`. The Django API must also be running (`uv run manage.py runserver`) for the frontend to have anything to talk to — see [Getting Started](#getting-started) above.

**CORS:** the backend uses `django-cors-headers` to explicitly allow requests from the frontend's origin (`CORS_ALLOWED_ORIGINS` in `docsasa/settings.py`). Configured for local dev (`localhost:5173`/`127.0.0.1:5173`) and the deployed frontend URL (see [Deployment](#deployment)).

### Frontend design notes

- **Token storage in `localStorage`** — standard, simple approach for a token-auth SPA. Never used for anything patient-facing, since patients never authenticate.
- **`ProtectedRoute` only checks that a token *exists***, not that it's still valid — an expired/revoked token is instead caught the first time a protected API call actually fails with a 401, at which point the user is redirected to login. No proactive token verification on route load; a reasonable v1 simplification.
- **The manage-appointment link is safe as a public route specifically because `Appointment.id` is a UUID** (see [System Design → Key Decisions, #8](#key-decisions)) — knowing the link is what grants viewing access, and actually changing anything still requires the OTP step.

## Deployment

**Live application:** https://docsasa-frontend.onrender.com
**Live API base URL:** https://docsasa-backend.onrender.com/api/v1/
**Django admin:** https://docsasa-backend.onrender.com/admin/

> Note: the bare backend URL (`https://docsasa-backend.onrender.com/` with no path) has no landing page and will correctly return a 404 — the backend is API-only, with real routes living under `/api/v1/...` and `/admin/`. That 404 is expected, not a sign of a broken deploy.

### Hosting

Both the backend (Django + DRF) and frontend (React static build) are deployed on **Render**, provisioned together from a single [`render.yaml`](./render.yaml) Blueprint at the repo root:

- **`docsasa-backend`** — a Python web service running `gunicorn`, on Render's free instance tier.
- **`docsasa-frontend`** — a static site, built via `npm run build` and served directly by Render (free tier, static sites have no paid tier to begin with).
- **`docsasa-db`** — a free-tier PostgreSQL instance. Render's free Postgres expires 30 days after creation (with a grace period after), which was an acceptable trade-off for this assessment's ~1-month timeline; a paid instance (~$6–7/mo) would be the natural next step for longer-term hosting.

**Branch & auto-deploy:** Render is configured to deploy from **`main`**. Any push to `main` — including a merged pull request — triggers an automatic rebuild and redeploy of both services. *(A GitHub Actions pipeline that runs the test suite on every pull request, gating this auto-deploy, is planned next — see [Roadmap](#roadmap).)*

**Cold starts:** Render's free web service tier spins the backend down after ~15 minutes of no traffic. The first request after a period of inactivity can take 30–60 seconds to respond while the container restarts — this is expected free-tier behavior, not a bug. Subsequent requests are fast until it goes idle again.

### Environment & secrets

Non-sensitive config lives directly in `render.yaml` (e.g. `MAX_DOCTORS`, `MIN_BOOKING_LEAD_MINUTES`, service URLs). Secrets (`BREVO_API_KEY`, `DEFAULT_FROM_EMAIL`, `DJANGO_SUPERUSER_*`) are marked `sync: false` in the Blueprint, meaning they're **not** committed to the repo — they're entered directly in Render's dashboard per-service.

### Email delivery

Production email uses **Brevo's transactional email API** (via `django-anymail`), not SMTP — this was a deliberate correction, not the original plan: Render's free web services block outbound traffic on the SMTP ports (25/465/587) entirely, so the initially-planned SMTP relay silently couldn't work on the free tier. Switching to Brevo's HTTP API (port 443, not blocked) resolved this. *(This debugging process — and how AI tooling helped diagnose it — is covered in the AI Reflection section, still to be added.)*

A booking-confirmation or OTP email failing to send (e.g. during Brevo's new-account activation review) is handled differently depending on which email it is:
- **Booking confirmation** — failure is swallowed; the booking itself still succeeds, since losing a confirmation email is far less harmful than losing a real appointment over a notification hiccup.
- **OTP code** — failure is surfaced as a clear error to the caller, since the whole point of that email *is* its delivery; silently succeeding would leave a patient stuck with no way to verify.

### Superuser bootstrap

Since Render's free web services don't include Shell/SSH access, the initial Django superuser is created automatically as part of the build command (`createsuperuser --noinput`, using `DJANGO_SUPERUSER_USERNAME`/`EMAIL`/`PASSWORD` env vars), guarded with `|| true` so it harmlessly no-ops on every subsequent deploy once the account already exists.

## API Reference

> Base URL: `/api/v1/`

**Authentication:** staff (receptionists) authenticate via DRF token auth — `POST /api/v1/auth/login/` with `{"username": ..., "password": ...}` returns `{"token": "..."}`. Include it on subsequent requests as an `Authorization: Token <token>` header. Patients never authenticate; unauthenticated requests are the expected, normal path for patient self-service (see [System Design → Key Decisions, #9](#key-decisions)).

**Required (per assessment spec):**

| Method | Endpoint                                       | Description                                                                 |
|--------|--------------------------------------------------|-------------------------------------------------------------------------------|
| POST   | `/appointments/`                               | Book a slot. No OTP required. Validates it falls within the doctor's working hours, isn't in the past (or within `MIN_BOOKING_LEAD_MINUTES`), and isn't already taken. |
| GET    | `/doctors/{id}/availability/?date=YYYY-MM-DD`  | Return all available 30-minute slots for a doctor on a given date.           |
| PATCH  | `/appointments/{id}/cancel/`                   | Cancel an appointment with a required `reason`. Requires a valid `otp_code` unless the request is from an authenticated staff `User` (token auth). Errors if already cancelled. |
| PATCH  | `/appointments/{id}/reschedule/`               | Move an appointment to a new slot, validated as a fresh booking. Requires a valid `otp_code` unless the request is from an authenticated staff `User`. Errors if already cancelled. |

**Bonus (per assessment spec):**

| Method | Endpoint                          | Description                                                        |
|--------|-------------------------------------|----------------------------------------------------------------------|
| GET    | `/patients/{id}/appointments/`   | Upcoming (booked, future-dated) appointments for a patient, sorted by date. **Staff-only** (`IsAuthenticated`) — deliberately not public, since `Patient.id` is a plain sequential integer and exposing another person's appointment history by guessable ID would be a privacy leak. Patients access their own appointment individually via the UUID link instead (see [System Design → Key Decisions, #8 and #10](#key-decisions)). |
| —      | *(validation rule)*                | Bookings are rejected if the slot starts within `MIN_BOOKING_LEAD_MINUTES` (default 60) of now. ✅ implemented |

**Additional (not required, added for completeness):**

| Method | Endpoint                                  | Description                                     |
|--------|--------------------------------------------|---------------------------------------------------|
| POST   | `/appointments/{id}/request-otp/`         | Request a one-time code for `cancel` or `reschedule`, emailed to the patient on file (console-printed in local dev). |
| POST   | `/auth/login/`                            | Staff login — exchanges username/password for a DRF auth token.   |
| GET    | `/doctors/`                               | List all doctors — public.                          |
| POST   | `/doctors/`                               | Create a doctor — **staff-only**. Enforces the `MAX_DOCTORS` cap. |
| GET    | `/doctors/{id}/`                          | Retrieve a doctor, including their nested working hours — public. |
| PATCH/PUT | `/doctors/{id}/`                       | Edit a doctor's name/specialty — **staff-only**.    |
| POST   | `/doctors/{id}/working-hours/`            | Set a doctor's hours for one weekday — **staff-only**. Upserts: posting the same weekday again updates the existing row rather than creating a duplicate (enforced by the `unique_doctor_weekday` constraint). |
| DELETE | `/doctors/{id}/working-hours/?weekday=N`  | Remove a weekday's hours entirely — **staff-only**. No row for a weekday means the doctor is off that day. |
| GET    | `/appointments/`                          | List all appointments, optionally filtered by `?doctor=`, `?date=`, `?status=` — **staff-only**. Merged into the same view/URL as booking (`POST`), since it's the same resource — method distinguishes intent. |
| GET    | `/appointments/{id}/`                     | Retrieve a single appointment *(not yet built)*    |
| GET    | `/appointments/history/`                  | Appointment history / audit trail *(not yet built)* |
| GET    | `/dashboard/stats/`                       | Appointment statistics (booked/cancelled/etc.) *(not yet built)* |

All endpoints above marked without "(not yet built)" have been both manually verified end-to-end against a running server and covered by the automated test suite (see [Testing](#testing)).

## Testing

Automated tests (29 total) cover both the service layer and the API layer on top of it, in `appointments/tests.py`, run with:

```bash
uv run manage.py test appointments doctors
```

**Service-layer coverage** (calling `services.py` functions directly, no HTTP):
- Slot generation (correct count/spacing, doctor's day off, dangling-remainder edge case)
- Booking success and rejection paths (double-booking, outside working hours, on a doctor's day off)
- Patient record reuse by email across multiple bookings
- **The database `UniqueConstraint` itself**, tested by bypassing the service layer entirely and inserting directly — proving the guarantee holds even independent of application logic
- Cancellation (success, required reason, rejecting a double-cancel, slot freed afterward)
- Rescheduling (success, original slot freed, rejecting a reschedule onto an already-taken slot **and confirming the original booking survives untouched**, rejecting reschedule of a cancelled appointment)

**API-layer coverage** (using DRF's test client against real views/urls):
- Booking through `POST /appointments/` as an anonymous request, confirming `booked_by` is correctly null
- `GET /appointments/` correctly requires staff authentication (401 when anonymous, 200 with expected data when authenticated)
- OTP verification: cancelling without a code is rejected (400, `otp_code` flagged), cancelling with a valid code succeeds, and an authenticated staff user can cancel **without** any code at all — proving the "staff exempt from OTP" design decision is actually enforced, not just documented
- Doctor endpoints: public `GET /doctors/`, staff-only `POST /doctors/` and `POST /doctors/{id}/working-hours/` (401 when anonymous), and the working-hours **upsert** behavior (posting the same weekday twice updates the same row rather than creating a duplicate, confirmed both via the response `id` and a direct DB count)

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
- [x] `GET /patients/{id}/appointments` — upcoming appointments for a patient, sorted by date. Implemented as staff-only, not public (see API Reference note).
- [x] Reject bookings that start within 1 hour of now — implemented via `MIN_BOOKING_LEAD_MINUTES`

**Deferred design decisions (see [System Design → Deferred to Future Iterations](#deferred-to-future-iterations)):**
- [ ] `DoctorTimeOff` — let a doctor block off a day or date range
- [ ] Split working shifts within a single day (e.g. a lunch-hour gap)
- [ ] Automatic conflict resolution when a doctor's hours change (currently: grandfather + flag for manual review)
- [ ] Role-based permissions distinguishing patients from receptionists at the API layer
- [ ] Phone/SMS-based OTP verification (v1 is email-only)
- [ ] Rate limiting on OTP requests per appointment

**Other possible extensions:**
- [x] Doctor-side dashboard for managing their own schedule — implemented as a **staff**-facing "Doctors" page (`/staff/doctors`), not a doctor login, per the design decision that doctors remain passive in v1
- [ ] Rate limiting on the booking endpoint
- [ ] Update `CORS_ALLOWED_ORIGINS` and `FRONTEND_BASE_URL` to the real deployed frontend URL once hosted (currently configured for local dev only)
- [ ] Proactive token validation on protected frontend routes, rather than only discovering an expired token on the first failed API call

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes
4. Push to the branch and open a Pull Request

## License

 MIT.