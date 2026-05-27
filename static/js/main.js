/**
 * CivicConnect – main.js
 * Shared utility functions used across all pages
 */

// ─── Auth Helpers ─────────────────────────────────────────────
async function getSession() {
  try {
    const res = await fetch("/api/me", { credentials: "include" });
    return await res.json();
  } catch {
    return { authenticated: false };
  }
}

async function requireAuth() {
  const session = await getSession();
  if (!session.authenticated) {
    window.location.href = "/login";
    return null;
  }
  return session;
}

async function requireAdmin() {
  const session = await getSession();
  if (!session.authenticated || session.role !== "admin") {
    window.location.href = "/login";
    return null;
  }
  return session;
}

async function logout() {
  await fetch("/api/logout", {
    method: "POST",
    credentials: "include",
    headers: { "X-CSRF-Token": getCsrfToken() },
  });
  window.location.href = "/login";
}

// ─── UI Helpers ───────────────────────────────────────────────
function showMsg(id, text, type = "error") {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = `msg ${type}`;
}

function hideMsg(id) {
  const el = document.getElementById(id);
  if (el) el.className = "msg hidden";
}

function setLoading(btnId, loading, defaultText) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  btn.disabled = loading;
  btn.textContent = loading ? "Please wait…" : defaultText;
}

// ─── Badge Renderer ───────────────────────────────────────────
function statusBadge(status) {
  const cls = status.toLowerCase().replace(" ", "-");
  return `<span class="badge status-${cls}">${status}</span>`;
}

function priorityBadge(priority) {
  return `<span class="badge pri-${priority.toLowerCase()}">${priority}</span>`;
}

function categoryBadge(category) {
  return `<span class="badge cat">${category}</span>`;
}

// ─── Format Date ──────────────────────────────────────────────
function formatDate(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return isNaN(d) ? dateStr : d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

// ─── Truncate Text ────────────────────────────────────────────
function truncate(str, max = 40) {
  if (!str) return "—";
  return str.length > max ? str.substring(0, max) + "…" : str;
}

// ─── CSRF Helper ──────────────────────────────────────────────
function getCsrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

// ─── API Wrapper ──────────────────────────────────────────────
async function apiFetch(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const csrfHeaders = ["POST", "PATCH", "PUT", "DELETE"].includes(method)
    ? { "X-CSRF-Token": getCsrfToken() }
    : {};

  const defaults = {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...csrfHeaders,
    },
  };

  // Allow callers to pass extra headers without clobbering CSRF
  const merged = {
    ...defaults,
    ...options,
    headers: { ...defaults.headers, ...(options.headers || {}) },
  };

  const res = await fetch(url, merged);
  const data = await res.json();
  return { ok: res.ok, status: res.status, data };
}

// ─── Enter Key Submit ─────────────────────────────────────────
function onEnter(callback) {
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) callback();
  });
}