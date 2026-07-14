import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";

export default function Dashboard() {
  const [appointments, setAppointments] = useState([]);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ date: "", status: "" });

  const [cancellingId, setCancellingId] = useState(null);
  const [reason, setReason] = useState("");

  const [reschedulingId, setReschedulingId] = useState(null);
  const [newDate, setNewDate] = useState("");
  const [slots, setSlots] = useState([]);
  const [newSlot, setNewSlot] = useState(null);

  const navigate = useNavigate();

  function load() {
    const params = new URLSearchParams();
    if (filters.date) params.set("date", filters.date);
    if (filters.status) params.set("status", filters.status);
    api
      .get(`/appointments/?${params.toString()}`, { auth: true })
      .then(setAppointments)
      .catch((e) => {
        if (e.message.includes("credentials")) {
          localStorage.removeItem("docsasa_staff_token");
          navigate("/staff/login");
        } else {
          setError(e.message);
        }
      });
  }

  useEffect(load, [filters]);

  function logout() {
    localStorage.removeItem("docsasa_staff_token");
    navigate("/staff/login");
  }

  function closeAllActions() {
    setCancellingId(null);
    setReason("");
    setReschedulingId(null);
    setNewDate("");
    setSlots([]);
    setNewSlot(null);
  }

  async function handleCancel(appointmentId) {
    setError(null);
    try {
      // Authenticated staff requests skip OTP — the backend only requires
      // otp_code when request.user.is_authenticated is false.
      await api.patch(`/appointments/${appointmentId}/cancel/`, { reason }, { auth: true });
      closeAllActions();
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  function startReschedule(appointment) {
    closeAllActions();
    setReschedulingId(appointment.id);
  }

  useEffect(() => {
    if (!reschedulingId || !newDate) {
      setSlots([]);
      return;
    }
    const appointment = appointments.find((a) => a.id === reschedulingId);
    if (!appointment) return;
    setNewSlot(null);
    api
      .get(`/doctors/${appointment.doctor}/availability/?date=${newDate}`)
      .then(setSlots)
      .catch((e) => setError(e.message));
  }, [newDate, reschedulingId]);

  async function handleReschedule(appointmentId) {
    setError(null);
    try {
      await api.patch(
        `/appointments/${appointmentId}/reschedule/`,
        { new_date: newDate, new_start_time: newSlot.start_time },
        { auth: true }
      );
      closeAllActions();
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="max-w-5xl mx-auto mt-10 p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-xl font-semibold">Appointments</h1>
        <div className="flex gap-4">
          <a href="/staff/doctors" className="text-blue-600 underline text-sm self-center">
            Manage doctors
          </a>
          <button onClick={logout} className="text-sm text-gray-500 underline">
            Log out
          </button>
        </div>
      </div>

      <div className="flex gap-2 mb-4">
        <input
          type="date"
          className="border rounded p-2"
          value={filters.date}
          onChange={(e) => setFilters({ ...filters, date: e.target.value })}
        />
        <select
          className="border rounded p-2"
          value={filters.status}
          onChange={(e) => setFilters({ ...filters, status: e.target.value })}
        >
          <option value="">All statuses</option>
          <option value="booked">Booked</option>
          <option value="cancelled">Cancelled</option>
          <option value="completed">Completed</option>
        </select>
      </div>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <table className="w-full text-sm bg-white rounded shadow overflow-hidden">
        <thead className="bg-gray-100 text-left">
          <tr>
            <th className="p-2">Patient</th>
            <th className="p-2">Doctor</th>
            <th className="p-2">Date</th>
            <th className="p-2">Time</th>
            <th className="p-2">Status</th>
            <th className="p-2">Actions</th>
          </tr>
        </thead>
        <tbody>
          {appointments.map((a) => (
            <tr key={a.id} className="border-t align-top">
              <td className="p-2">{a.patient.name}</td>
              <td className="p-2">{a.doctor_name}</td>
              <td className="p-2">{a.date}</td>
              <td className="p-2">{a.start_time.slice(0, 5)}</td>
              <td className="p-2 capitalize">{a.status}</td>
              <td className="p-2 min-w-[220px]">
                {a.status === "booked" && cancellingId !== a.id && reschedulingId !== a.id && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => {
                        closeAllActions();
                        setCancellingId(a.id);
                      }}
                      className="text-red-600 underline text-xs"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => startReschedule(a)}
                      className="text-blue-600 underline text-xs"
                    >
                      Reschedule
                    </button>
                  </div>
                )}

                {cancellingId === a.id && (
                  <div className="flex gap-1 items-center">
                    <input
                      autoFocus
                      placeholder="Reason"
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      className="border rounded p-1 text-xs w-24"
                    />
                    <button
                      onClick={() => handleCancel(a.id)}
                      disabled={!reason}
                      className="bg-red-600 text-white rounded px-2 py-1 text-xs disabled:bg-gray-300"
                    >
                      Confirm
                    </button>
                    <button onClick={closeAllActions} className="text-gray-500 text-xs underline">
                      Back
                    </button>
                  </div>
                )}

                {reschedulingId === a.id && (
                  <div className="space-y-1">
                    <input
                      type="date"
                      min={new Date().toISOString().split("T")[0]}
                      value={newDate}
                      onChange={(e) => setNewDate(e.target.value)}
                      className="border rounded p-1 text-xs w-full"
                    />
                    {newDate && slots.length === 0 && (
                      <p className="text-xs text-gray-500">No slots available.</p>
                    )}
                    {slots.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {slots.map((slot) => (
                          <button
                            key={slot.start_time}
                            onClick={() => setNewSlot(slot)}
                            className={`text-xs px-1.5 py-0.5 rounded border ${
                              newSlot?.start_time === slot.start_time
                                ? "bg-blue-600 text-white"
                                : "bg-white"
                            }`}
                          >
                            {slot.start_time.slice(0, 5)}
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="flex gap-1">
                      <button
                        onClick={() => handleReschedule(a.id)}
                        disabled={!newSlot}
                        className="bg-blue-600 text-white rounded px-2 py-1 text-xs disabled:bg-gray-300"
                      >
                        Confirm
                      </button>
                      <button onClick={closeAllActions} className="text-gray-500 text-xs underline">
                        Back
                      </button>
                    </div>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}