const state = {
  telegramId: null,
  referralLink: null,
};

const banner = document.getElementById("error-banner");
const tasksContainer = document.getElementById("tasks");
const refCount = document.getElementById("ref-count");
const copyRefButton = document.getElementById("copy-ref");
const balancePro = document.getElementById("balance-pro");
const balanceUsd = document.getElementById("balance-usd");
const withdrawForm = document.getElementById("withdraw-form");

function showError(message) {
  banner.textContent = message;
  banner.classList.remove("hidden");
}

function clearError() {
  banner.classList.add("hidden");
  banner.textContent = "";
}

async function apiFetch(path, options = {}) {
  const headers = options.headers || {};
  if (state.telegramId) {
    headers["x-telegram-id"] = state.telegramId;
  }
  return fetch(path, { ...options, headers });
}

async function initAuth() {
  const webApp = window.Telegram?.WebApp;
  if (!webApp) {
    showError("Telegram WebApp недоступний.");
    return;
  }
  const initData = webApp.initData;
  if (!initData) {
    showError("Немає даних авторизації.");
    return;
  }
  const response = await fetch("/api/auth/telegram", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ initData }),
  });
  if (!response.ok) {
    showError("Помилка авторизації. Спробуйте пізніше.");
    return;
  }
  clearError();
  const data = await response.json();
  state.telegramId = data.telegram_id;
  balancePro.textContent = data.pro_balance;
  balanceUsd.textContent = data.usd_balance;
  await Promise.all([loadTasks(), loadReferrals()]);
}

async function loadTasks() {
  const response = await apiFetch("/api/offers");
  if (!response.ok) {
    showError("Не вдалося завантажити завдання.");
    return;
  }
  const data = await response.json();
  tasksContainer.innerHTML = "";
  data.tasks.forEach((task) => {
    const card = document.createElement("div");
    card.className = "task";
    if (task.display_type === "limited") {
      const badge = document.createElement("div");
      badge.className = "badge";
      badge.textContent = "ЛІМІТОВАНЕ";
      card.appendChild(badge);
    }
    const title = document.createElement("h3");
    title.textContent = task.title;
    card.appendChild(title);

    const reward = document.createElement("p");
    reward.textContent = `Нагорода: ${task.reward_pro} PRO / ${task.reward_usd} USD`;
    card.appendChild(reward);

    const button = document.createElement("button");
    if (task.type === "channel_subscribe") {
      button.textContent = "Перевірити підписку";
      button.addEventListener("click", () => {
        window.location.href = task.channel_url;
      });
    } else {
      button.textContent = "Відкрити офер";
      button.addEventListener("click", () => {
        window.open(task.offer_url, "_blank");
      });
    }
    card.appendChild(button);
    tasksContainer.appendChild(card);
  });
}

async function loadReferrals() {
  const response = await apiFetch("/api/referrals");
  if (!response.ok) {
    showError("Не вдалося завантажити рефералів.");
    return;
  }
  const data = await response.json();
  refCount.textContent = data.total;
  state.referralLink = data.referral_link;
}

copyRefButton.addEventListener("click", async () => {
  if (!state.referralLink) return;
  await navigator.clipboard.writeText(state.referralLink);
  copyRefButton.textContent = "Скопійовано!";
  setTimeout(() => {
    copyRefButton.textContent = "Скопіювати реферальне посилання";
  }, 2000);
});

withdrawForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    amount_pro: Number(document.getElementById("withdraw-pro").value),
    amount_usd: Number(document.getElementById("withdraw-usd").value),
    details: document.getElementById("withdraw-details").value,
  };
  const response = await apiFetch("/api/withdraw", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (response.ok) {
    showError("✅ Заявку на вивід прийнято.");
  } else {
    showError("Не вдалося відправити заявку.");
  }
});

const tabs = document.querySelectorAll(".bottom-nav button");
const tabPanels = document.querySelectorAll(".tab");

for (const tab of tabs) {
  tab.addEventListener("click", () => {
    tabs.forEach((item) => item.classList.remove("active"));
    tabPanels.forEach((panel) => panel.classList.remove("active"));
    tab.classList.add("active");
    const target = document.getElementById(tab.dataset.tab);
    target.classList.add("active");
  });
}

initAuth();
