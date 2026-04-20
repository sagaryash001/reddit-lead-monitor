const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8000",
  pollMinutes: 1,
  enabled: true
};

function normalizeBaseUrl(value) {
  return (value || DEFAULTS.backendUrl).trim().replace(/\/+$/, "");
}

async function loadSettings() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
  return {
    backendUrl: normalizeBaseUrl(stored.backendUrl),
    pollMinutes: Math.max(1, Number(stored.pollMinutes) || DEFAULTS.pollMinutes),
    enabled: stored.enabled !== false
  };
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  return response.json();
}

function renderStats(stats) {
  const target = document.getElementById("stats-summary");
  target.textContent =
    `matched ${stats.matched}, qualified ${stats.qualified}, contacted ${stats.contacted}`;
}

function renderAlerts(alerts) {
  const target = document.getElementById("alerts-list");
  const meta = document.getElementById("alert-meta");

  if (!alerts.length) {
    target.innerHTML = '<div class="small muted">No alerts yet.</div>';
    meta.textContent = "";
    return;
  }

  meta.textContent = `${alerts.length} recent alert${alerts.length === 1 ? "" : "s"}`;
  target.innerHTML = alerts
    .map(
      (alert) => `
        <article class="list-item">
          <div class="list-item-title">${alert.title}</div>
          <div class="small">${alert.message}</div>
          <a class="small link" href="${alert.permalink}" target="_blank" rel="noreferrer">Open Reddit</a>
        </article>
      `
    )
    .join("");
}

async function refreshPopup(triggerPoll = false) {
  const settings = await loadSettings();
  document.getElementById("backend-url").textContent = settings.backendUrl;

  if (!settings.enabled) {
    document.getElementById("backend-status").textContent = "Disabled";
    document.getElementById("stats-summary").textContent = "Extension polling is turned off.";
    renderAlerts([]);
    return;
  }

  if (triggerPoll) {
    await chrome.runtime.sendMessage({ type: "poll-now" });
  }

  try {
    const [health, stats, alerts, runtimeState] = await Promise.all([
      fetchJson(`${settings.backendUrl}/health`),
      fetchJson(`${settings.backendUrl}/api/stats`),
      fetchJson(`${settings.backendUrl}/api/alerts?limit=8&order=desc`),
      chrome.runtime.sendMessage({ type: "get-runtime-state" })
    ]);

    document.getElementById("backend-status").textContent = health.ok ? "Online" : "Unavailable";
    renderStats(stats);
    renderAlerts(alerts);

    if (runtimeState?.lastError) {
      document.getElementById("backend-status").textContent = "Warning";
      document.getElementById("alert-meta").textContent = runtimeState.lastError;
    }
  } catch (error) {
    document.getElementById("backend-status").textContent = "Offline";
    document.getElementById("stats-summary").textContent = String(error);
    document.getElementById("alerts-list").innerHTML =
      '<div class="small muted">The extension could not reach the backend.</div>';
  }
}

document.getElementById("refresh-button").addEventListener("click", () => {
  refreshPopup(true);
});

document.getElementById("open-dashboard-button").addEventListener("click", async () => {
  const settings = await loadSettings();
  chrome.tabs.create({ url: settings.backendUrl });
});

document.getElementById("open-options-button").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

refreshPopup();
