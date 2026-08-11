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
    const prior = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = prior; }, 1400);
  });
});
