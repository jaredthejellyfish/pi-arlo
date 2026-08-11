const $ = (selector) => document.querySelector(selector);

function safeSlug(value) {
  return value.toLowerCase().trim().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "camera";
}

function showError(message) {
  const box = $("#pair-error");
  if (!box) return;
  box.textContent = message;
  box.classList.remove("hidden");
}

async function responseJson(response) {
  let body = {};
  try { body = await response.json(); } catch (_) { /* no body */ }
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

async function pollPairing(session) {
  const response = await fetch(`/api/pair/${session}`, {cache: "no-store"});
  const result = await responseJson(response);
  if (result.expired) throw new Error(result.message);
  if (result.wifi_detected) {
    $("#check-wifi").classList.add("done");
    $("#check-wifi span").textContent = "✓";
  }
  if (result.dhcp_detected) {
    $("#check-dhcp").classList.add("done");
    $("#check-dhcp span").textContent = "✓";
  }
  if (result.registered) {
    $("#check-api").classList.add("done");
    $("#check-api span").textContent = "✓";
    showFinish(result.camera);
    return;
  }
  setTimeout(() => pollPairing(session).catch((error) => showError(error.message)), 2000);
}

function showFinish(camera) {
  $("#pair-progress").classList.add("hidden");
  $("#pair-finish").classList.remove("hidden");
  document.querySelector('[data-step="2"]').classList.remove("active");
  document.querySelector('[data-step="2"]').classList.add("complete");
  document.querySelector('[data-step="3"]').classList.add("active");
  $("#found-model").textContent = camera.hostname;
  $("#found-details").textContent = `${camera.serial} · ${camera.mac} · ${camera.ip}`;
  for (const field of ["serial", "hostname", "mac", "ip"]) $(`#${field}`).value = camera[field];
  $("#name").focus();
}

const startButton = $("#start-pairing");
if (startButton) {
  startButton.addEventListener("click", async () => {
    startButton.disabled = true;
    startButton.innerHTML = '<span class="button-spinner" aria-hidden="true"></span> Opening secure pairing…';
    $("#pair-error").classList.add("hidden");
    try {
      const result = await responseJson(await fetch("/api/pair/start", {method: "POST"}));
      $("#pair-start").classList.add("hidden");
      $("#pair-progress").classList.remove("hidden");
      document.querySelector('[data-step="1"]').classList.replace("active", "complete");
      document.querySelector('[data-step="2"]').classList.add("active");
      pollPairing(result.session).catch((error) => showError(error.message));
    } catch (error) {
      showError(error.message);
      startButton.disabled = false;
      startButton.innerHTML = 'Try pairing again <span aria-hidden="true">→</span>';
    }
  });
}

const nameInput = $("#name");
const slugInput = $("#slug");
if (nameInput && slugInput) {
  let userChangedSlug = false;
  slugInput.addEventListener("input", () => { userChangedSlug = true; });
  nameInput.addEventListener("input", () => {
    if (!userChangedSlug) slugInput.value = safeSlug(nameInput.value);
  });
}

document.querySelectorAll(".copy-button").forEach((button) => {
  button.addEventListener("click", async () => {
    const source = document.getElementById(button.dataset.copy);
    await navigator.clipboard.writeText(source.innerText);
    const prior = button.innerHTML;
    button.innerHTML = '<span aria-hidden="true">✓</span> Copied';
    setTimeout(() => { button.innerHTML = prior; }, 1400);
  });
});

const CAMERA_REFRESH_MS = 7000;
let cameraRefreshTimer;
let cameraRefreshInFlight = false;

function setMetric(root, valueSelector, unitSelector, value) {
  const valueNode = root.querySelector(valueSelector);
  const unitNode = root.querySelector(unitSelector);
  if (!valueNode || !unitNode) return;
  const available = value !== null && value !== undefined && value !== "";
  valueNode.textContent = available ? value : "—";
  unitNode.classList.toggle("hidden", !available);
}

function updateCameraCard(card, camera) {
  const state = card.querySelector("[data-camera-state]");
  if (state) {
    state.classList.remove("online", "sleeping", "offline");
    state.classList.add(camera.state);
    const label = state.querySelector("span");
    if (label) label.textContent = camera.state[0].toUpperCase() + camera.state.slice(1);
  }
  setMetric(card, "[data-camera-battery]", "[data-battery-unit]", camera.battery);
  setMetric(card, "[data-camera-signal]", "[data-signal-unit]", camera.signal);
}

function statusText(value) {
  if (value === null) return "null";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function updateCameraDetail(root, camera) {
  const connection = root.querySelector("[data-camera-connection]");
  if (connection) {
    connection.classList.remove("up", "idle", "down");
    connection.classList.add(camera.state === "online" ? "up" : camera.state === "sleeping" ? "idle" : "down");
    connection.title = camera.state[0].toUpperCase() + camera.state.slice(1);
  }

  const list = root.querySelector("[data-camera-status-list]");
  if (!list) return;
  const entries = Object.entries(camera.status || {});
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "sleeping-state";
    const icon = document.createElement("span");
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "◌";
    const copy = document.createElement("p");
    const title = document.createElement("strong");
    title.textContent = "No live report";
    const note = document.createElement("small");
    note.textContent = "The camera is sleeping or has not reported status yet.";
    copy.append(title, note);
    empty.append(icon, copy);
    list.replaceChildren(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const [key, value] of entries) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = key;
    description.textContent = statusText(value);
    row.append(term, description);
    fragment.append(row);
  }
  list.replaceChildren(fragment);
}

function setRefreshIndicator(state, updatedAt) {
  document.querySelectorAll("[data-refresh-indicator]").forEach((indicator) => {
    indicator.classList.toggle("refreshing", state === "refreshing");
    indicator.classList.toggle("stale", state === "stale");
    const label = indicator.querySelector("[data-refresh-label]");
    if (!label) return;
    if (state === "refreshing") label.textContent = "Refreshing…";
    else if (state === "stale") label.textContent = "Update delayed";
    else label.textContent = "Updated just now";
    if (updatedAt) indicator.title = `Last updated ${new Date(updatedAt * 1000).toLocaleTimeString()}`;
  });
}

async function refreshCameraStatuses() {
  clearTimeout(cameraRefreshTimer);
  if (cameraRefreshInFlight) {
    cameraRefreshTimer = setTimeout(refreshCameraStatuses, CAMERA_REFRESH_MS);
    return;
  }

  cameraRefreshInFlight = true;
  setRefreshIndicator("refreshing");
  try {
    const statusUrl = new URL("/api/cameras/status", window.location.origin);
    const payload = await responseJson(await fetch(statusUrl, {cache: "no-store"}));
    document.querySelectorAll("[data-camera-serial]").forEach((card) => {
      const camera = payload.cameras[card.dataset.cameraSerial];
      if (camera) updateCameraCard(card, camera);
    });
    const detail = document.querySelector("[data-camera-detail]");
    if (detail) {
      const camera = payload.cameras[detail.dataset.cameraDetail];
      if (camera) updateCameraDetail(detail, camera);
    }
    setRefreshIndicator("current", payload.updated_at);
  } catch (error) {
    console.warn("Camera status refresh failed", error);
    setRefreshIndicator("stale");
  } finally {
    cameraRefreshInFlight = false;
    cameraRefreshTimer = setTimeout(refreshCameraStatuses, CAMERA_REFRESH_MS);
  }
}

if (document.querySelector("[data-camera-serial], [data-camera-detail]")) {
  cameraRefreshTimer = setTimeout(refreshCameraStatuses, 1000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshCameraStatuses();
  });
}
