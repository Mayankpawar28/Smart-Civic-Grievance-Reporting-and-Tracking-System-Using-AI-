/**
 * CivicConnect – avatar.js
 * Shared avatar upload, display and removal logic.
 * Call initAvatar() after profile data is loaded.
 */

/** Read the CSRF token from the cookie set by the server. */
function getCsrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

/**
 * Set avatar display everywhere on the page.
 * @param {string} avatarUrl  - URL string, or "" / null for fallback
 * @param {string} fallbackLetter - single char to show when no photo
 */
function setAvatarDisplay(avatarUrl, fallbackLetter) {
  const letter = (fallbackLetter || "?").toUpperCase();

  // Sidebar small avatar
  const sbEl = document.getElementById("userAvatar");
  if (sbEl) {
    if (avatarUrl) {
      sbEl.innerHTML = `<img src="${avatarUrl}?t=${Date.now()}" alt="avatar">`;
    } else {
      sbEl.innerHTML = letter;
    }
  }

  // Profile drawer large avatar
  const pdEl = document.getElementById("pdAvatar");
  if (pdEl) {
    if (avatarUrl) {
      pdEl.innerHTML = `<img src="${avatarUrl}?t=${Date.now()}" alt="avatar">`;
    } else {
      pdEl.innerHTML = letter;
    }
  }

  // Show/hide remove button
  const removeBtn = document.getElementById("pdRemoveAvatar");
  if (removeBtn) {
    removeBtn.classList.toggle("hidden", !avatarUrl);
  }
}

/**
 * Wrap the pd-avatar element in the clickable upload wrapper.
 * Call this once after the profile drawer HTML is in the DOM.
 */
function initAvatarUpload() {
  const pdAvatar = document.getElementById("pdAvatar");
  if (!pdAvatar || pdAvatar.parentElement.classList.contains("pd-avatar-wrapper")) return;

  // Wrap in clickable div
  const wrapper = document.createElement("div");
  wrapper.className = "pd-avatar-wrapper";
  wrapper.title = "Change profile photo";

  const overlay = document.createElement("div");
  overlay.className = "pd-avatar-upload-overlay";
  overlay.innerHTML = "<span>📷</span>Change photo";

  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "image/png,image/jpeg,image/webp";
  fileInput.id = "avatarFileInput";

  pdAvatar.parentNode.insertBefore(wrapper, pdAvatar);
  wrapper.appendChild(pdAvatar);
  wrapper.appendChild(overlay);
  wrapper.appendChild(fileInput);

  wrapper.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) handleAvatarUpload(fileInput.files[0]);
  });
}

async function handleAvatarUpload(file) {
  if (file.size > 5 * 1024 * 1024) {
    showAvatarMsg("Photo must be under 5MB.", "error"); return;
  }
  if (!file.type.match(/image\/(png|jpeg|webp)/)) {
    showAvatarMsg("Only PNG, JPG or WEBP allowed.", "error"); return;
  }

  // Show spinner overlay on the avatar
  const pdEl = document.getElementById("pdAvatar");
  const spinner = document.createElement("div");
  spinner.className = "pd-avatar-spinner";
  spinner.id = "avatarSpinner";
  if (pdEl) pdEl.style.position = "relative", pdEl.appendChild(spinner);

  try {
    const fd = new FormData();
    fd.append("avatar", file);
    const res = await fetch("/api/profile/avatar", {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": getCsrfToken() },
      body: fd,
    });
    const data = await res.json();
    if (res.ok) {
      setAvatarDisplay(data.avatar_url, window._avatarFallbackLetter || "?");
      showAvatarMsg("Photo updated!", "success");
    } else {
      showAvatarMsg(data.error || "Upload failed.", "error");
    }
  } catch {
    showAvatarMsg("Network error. Try again.", "error");
  } finally {
    const sp = document.getElementById("avatarSpinner");
    if (sp) sp.remove();
    // Reset file input so same file can be re-selected
    const fi = document.getElementById("avatarFileInput");
    if (fi) fi.value = "";
  }
}

async function removeAvatar() {
  if (!confirm("Remove your profile photo?")) return;
  try {
    const res = await fetch("/api/profile/avatar", {
      method: "DELETE",
      credentials: "include",
      headers: { "X-CSRF-Token": getCsrfToken() },
    });
    if (res.ok) {
      setAvatarDisplay("", window._avatarFallbackLetter || "?");
      showAvatarMsg("Photo removed.", "success");
    }
  } catch {
    showAvatarMsg("Network error. Try again.", "error");
  }
}

function showAvatarMsg(text, type) {
  // Reuse existing msg element if on the page, else use a toast
  const existing = document.getElementById("msg");
  if (existing) {
    existing.textContent = text;
    existing.className = `msg ${type}`;
    setTimeout(() => { existing.className = "msg hidden"; }, 3500);
    return;
  }
  // Toast fallback
  let toast = document.getElementById("avatarToast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "avatarToast";
    toast.style.cssText = "position:fixed;bottom:5rem;left:50%;transform:translateX(-50%);padding:.6rem 1.2rem;border-radius:8px;font-size:.85rem;font-weight:600;z-index:2000;transition:opacity .3s";
    document.body.appendChild(toast);
  }
  toast.textContent = text;
  toast.style.background = type === "success" ? "#f0fdf4" : "#fef2f2";
  toast.style.color = type === "success" ? "#059669" : "#dc2626";
  toast.style.border = `1px solid ${type === "success" ? "#bbf7d0" : "#fecaca"}`;
  toast.style.opacity = "1";
  setTimeout(() => { toast.style.opacity = "0"; }, 3000);
}
