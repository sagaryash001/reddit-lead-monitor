const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8000",
  pollMinutes: 1,
  enabled: true
};

function normalizeBaseUrl(value) {
  const url = (value || DEFAULTS.backendUrl).trim();
  return url.replace(/\/+$/, "");
}

async function loadSettings() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
  return {
    backendUrl: normalizeBaseUrl(stored.backendUrl),
    pollMinutes: Math.max(1, Number(stored.pollMinutes) || DEFAULTS.pollMinutes),
    enabled: stored.enabled !== false
  };
}

async function setBadge(text) {
  await chrome.action.setBadgeBackgroundColor({ color: "#b84f2b" });
  await chrome.action.setBadgeText({ text });
}

async function primeAlertCursor(settings) {
  const state = await chrome.storage.local.get(["lastAlertId"]);
  if (typeof state.lastAlertId === "number") {
    return;
  }

  try {
    const response = await fetch(`${settings.backendUrl}/api/alerts/latest`);
    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }
    const payload = await response.json();
    await chrome.storage.local.set({
      lastAlertId: Number(payload.latest_id) || 0,
      lastError: ""
    });
    await setBadge("");
  } catch (error) {
    await chrome.storage.local.set({ lastError: String(error) });
    await setBadge("!");
  }
}

async function ensureAlarm() {
  const settings = await loadSettings();
  await chrome.alarms.clear("lead-monitor-poll");

  if (!settings.enabled) {
    await setBadge("off");
    return;
  }

  await chrome.alarms.create("lead-monitor-poll", { periodInMinutes: settings.pollMinutes });
  await primeAlertCursor(settings);
}

async function rememberAlertLink(alertId, url) {
  const state = await chrome.storage.local.get(["alertLinks"]);
  const alertLinks = state.alertLinks || {};
  alertLinks[String(alertId)] = url;

  const entries = Object.entries(alertLinks).slice(-50);
  await chrome.storage.local.set({ alertLinks: Object.fromEntries(entries) });
}

async function notifyAlert(alert, settings) {
  await rememberAlertLink(alert.id, alert.permalink || settings.backendUrl);
  await chrome.notifications.create(`lead-alert-${alert.id}`, {
    type: "basic",
    iconUrl: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7nWH0AAAAASUVORK5CYII=",
    title: alert.title,
    message: alert.message,
    priority: 2
  });
}

async function pollForAlerts() {
  const settings = await loadSettings();
  if (!settings.enabled) {
    return;
  }

  const state = await chrome.storage.local.get(["lastAlertId"]);
  if (typeof state.lastAlertId !== "number") {
    await primeAlertCursor(settings);
    return;
  }

  try {
    const response = await fetch(
      `${settings.backendUrl}/api/alerts?after_id=${state.lastAlertId}&limit=20&order=asc`
    );
    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }

    const alerts = await response.json();
    if (!Array.isArray(alerts) || alerts.length === 0) {
      await chrome.storage.local.set({ lastError: "" });
      await setBadge("");
      return;
    }

    for (const alert of alerts) {
      await notifyAlert(alert, settings);
    }

    const newest = alerts[alerts.length - 1];
    await chrome.storage.local.set({
      lastAlertId: newest.id,
      recentAlerts: alerts.slice(-20),
      lastError: ""
    });
    await setBadge(String(Math.min(alerts.length, 9)));
  } catch (error) {
    await chrome.storage.local.set({ lastError: String(error) });
    await setBadge("!");
  }
}

chrome.runtime.onInstalled.addListener(() => {
  ensureAlarm();
});

chrome.runtime.onStartup.addListener(() => {
  ensureAlarm();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "lead-monitor-poll") {
    pollForAlerts();
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "settings-updated") {
    chrome.storage.local.remove(["lastAlertId"]).then(() => ensureAlarm()).then(() => {
      sendResponse({ ok: true });
    });
    return true;
  }

  if (message?.type === "poll-now") {
    pollForAlerts().then(() => sendResponse({ ok: true }));
    return true;
  }

  if (message?.type === "get-runtime-state") {
    chrome.storage.local
      .get(["lastAlertId", "lastError", "recentAlerts"])
      .then((payload) => sendResponse(payload));
    return true;
  }

  return false;
});

chrome.notifications.onClicked.addListener(async (notificationId) => {
  const settings = await loadSettings();
  const match = notificationId.match(/^lead-alert-(\d+)$/);
  const state = await chrome.storage.local.get(["alertLinks"]);
  const alertLinks = state.alertLinks || {};
  const target = match ? alertLinks[match[1]] || settings.backendUrl : settings.backendUrl;
  await chrome.tabs.create({ url: target });
});
