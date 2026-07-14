import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const data = await api.post("/auth/login/", { username, password });
      localStorage.setItem("docsasa_staff_token", data.token);
      navigate("/staff/dashboard");
    } catch {
      setError("Invalid username or password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-sm mx-auto mt-24 p-6 bg-white rounded-lg shadow">
      <h1 className="text-xl font-semibold mb-4">Staff login</h1>
      <form onSubmit={handleSubmit}>
        <input
          required
          placeholder="Username"
          className="w-full border rounded p-2 mb-2"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          required
          type="password"
          placeholder="Password"
          className="w-full border rounded p-2 mb-4"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <p className="text-red-600 text-sm mb-2">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 text-white rounded p-2 font-medium"
        >
          {loading ? "Logging in…" : "Log in"}
        </button>
      </form>
      <div className="mt-4 text-center text-sm">
        <a href="/" className="text-gray-500 underline">
          Back to patient booking
        </a>
      </div>
    </div>
  );
}