const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8000",
  pollMinutes: 1,
  enabled: true
};

function normalizeBaseUrl(value) {
  return (value || DEFAULTS.backendUrl).trim().replace(/\/+$/, "");
}

async function loadOptions() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
  document.getElementById("backend-url").value = normalizeBaseUrl(stored.backendUrl);
  document.getElementById("poll-minutes").value = Math.max(1, Number(stored.pollMinutes) || 1);
  document.getElementById("enabled").checked = stored.enabled !== false;
}

async function saveOptions(event) {
  event.preventDefault();

  const backendUrl = normalizeBaseUrl(document.getElementById("backend-url").value);
  const pollMinutes = Math.max(1, Number(document.getElementById("poll-minutes").value) || 1);
  const enabled = document.getElementById("enabled").checked;

  await chrome.storage.sync.set({ backendUrl, pollMinutes, enabled });
  await chrome.runtime.sendMessage({ type: "settings-updated" });
  document.getElementById("save-status").textContent = "Saved. New alerts will now use this backend.";
}

document.getElementById("options-form").addEventListener("submit", saveOptions);

document.getElementById("open-dashboard-button").addEventListener("click", async () => {
  const backendUrl = normalizeBaseUrl(document.getElementById("backend-url").value);
  chrome.tabs.create({ url: backendUrl });
});

loadOptions();
