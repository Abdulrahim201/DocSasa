import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import BookAppointment from "./pages/patient/BookAppointment";
import ManageAppointment from "./pages/patient/ManageAppointment";
import Login from "./pages/staff/Login";
import Dashboard from "./pages/staff/Dashboard";
import Doctors from "./pages/staff/Doctors";

function ProtectedRoute({ children }) {
  const token = localStorage.getItem("docsasa_staff_token");
  return token ? children : <Navigate to="/staff/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<BookAppointment />} />
        <Route path="/appointments/:id" element={<ManageAppointment />} />
        <Route path="/staff/login" element={<Login />} />
        <Route
          path="/staff/dashboard"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/staff/doctors"
          element={
            <ProtectedRoute>
              <Doctors />
            </ProtectedRoute>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}