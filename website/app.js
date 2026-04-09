const registryModels = Array.isArray(window.__MODEL_CATALOG__)
  ? window.__MODEL_CATALOG__
  : [];

const models = registryModels
  .filter((model) => model && model.enabled_in_catalog !== false)
  .map((model) => ({
    id: model.id,
    name: model.display_name,
    family: model.family,
    category: model.category,
    deployment: model.deployment,
    badgeText: model.site_badge_text,
    badgeClass: model.site_badge_class,
    description: model.description,
    serverRequirements: Array.isArray(model.server_requirements)
      ? model.server_requirements
      : [],
    installName: model.install_name,
    installCommand: model.install_command || `ollama run ${model.install_name}`,
    officialUrl: model.official_url,
    ollamaUrl: model.ollama_url,
    sourceLabel: model.source_label,
    chips: Array.isArray(model.chips) ? model.chips : [],
    note: model.note || '',
    recommendedFor: Array.isArray(model.recommended_for)
      ? model.recommended_for
      : []
  }));

if (registryModels.length === 0 && window.console) {
  console.warn('Unified model registry is empty or unavailable for website catalog');
}

const QUICK_PRESETS = {
  pilot: {
    label: "Для пилота",
    title: "Рекомендованные модели для пилота",
    filter: (model) =>
      model.recommendedFor.includes("Пилот") ||
      model.deployment === "Локально"
  },
  production: {
    label: "Для production",
    title: "Рекомендованные модели для production",
    filter: (model) => model.recommendedFor.includes("Продакшн")
  },
  coding: {
    label: "Для кода",
    title: "Рекомендованные модели для coding-сценариев",
    filter: (model) =>
      model.recommendedFor.includes("Код") || model.category === "Код"
  },
  multimodal: {
    label: "Мультимодальные",
    title: "Рекомендованные мультимодальные модели",
    filter: (model) =>
      model.recommendedFor.includes("Мультимодальность") ||
      model.category === "Мультимодальная"
  },
  analytics: {
    label: "Для аналитики",
    title: "Рекомендованные модели для reasoning и аналитики",
    filter: (model) =>
      model.recommendedFor.includes("Аналитика") ||
      model.category === "Рассуждение"
  }
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function createRequirementsHtml(items) {
  return items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function createChipsHtml(chips) {
  return chips
    .map((chip) => `<span class="chip">${escapeHtml(chip)}</span>`)
    .join("");
}

function createLinksHtml(model) {
  return `
    <div class="card-links">
      <a class="link-btn" href="${escapeHtml(model.officialUrl)}" target="_blank" rel="noopener noreferrer">
        Официальная страница
      </a>
      <a class="link-btn link-btn-secondary" href="${escapeHtml(model.ollamaUrl)}" target="_blank" rel="noopener noreferrer">
        Страница модели в Ollama
      </a>
    </div>
  `;
}

function createModelCard(model) {
  return `
    <article class="model-card">
      <div class="model-top">
        <div>
          <h3>${escapeHtml(model.name)}</h3>
          <div class="model-provider">Семейство ${escapeHtml(model.family)}</div>
        </div>
        <span class="tag ${escapeHtml(model.badgeClass)}">${escapeHtml(model.badgeText)}</span>
      </div>

      <div class="requirements-box">
        <div class="requirements-title">Требования и характеристики</div>
        <ul class="requirements-list">
          ${createRequirementsHtml(model.serverRequirements)}
        </ul>
      </div>

      <div class="install-box">
        <div class="install-label">Имя модели для установки</div>
        <code class="install-command">${escapeHtml(model.installName)}</code>
      </div>

      <div class="install-box">
        <div class="install-label">Команда запуска через Ollama</div>
        <code class="install-command">${escapeHtml(model.installCommand)}</code>
      </div>

      <div class="model-desc">
        ${escapeHtml(model.description)}
      </div>

      <div class="chips">
        ${createChipsHtml(model.chips)}
      </div>

      ${createLinksHtml(model)}

      <div class="model-footer">
        <div class="model-note">
          ${escapeHtml(model.sourceLabel)}<br />
          ${escapeHtml(model.note)}
        </div>
        <span class="tag tag-cyan">${escapeHtml(model.installName)}</span>
      </div>
    </article>
  `;
}

function normalizeValue(value) {
  return String(value || "").trim().toLowerCase();
}

function getControls() {
  return {
    searchInput: document.getElementById("search"),
    familySelect: document.getElementById("provider"),
    categorySelect: document.getElementById("category"),
    deploymentSelect: document.getElementById("deployment")
  };
}

function filterModels() {
  const { searchInput, familySelect, categorySelect, deploymentSelect } =
    getControls();

  const searchValue = normalizeValue(searchInput?.value);
  const familyValue = familySelect?.value || "Все семейства";
  const categoryValue = categorySelect?.value || "Все категории";
  const deploymentValue = deploymentSelect?.value || "Все варианты";

  return models.filter((model) => {
    const haystack = [
      model.name,
      model.family,
      model.description,
      model.installName,
      model.installCommand,
      model.sourceLabel,
      model.note,
      ...model.serverRequirements,
      ...model.chips,
      ...model.recommendedFor
    ]
      .join(" ")
      .toLowerCase();

    const matchesSearch = !searchValue || haystack.includes(searchValue);
    const matchesFamily =
      familyValue === "Все семейства" || model.family === familyValue;
    const matchesCategory =
      categoryValue === "Все категории" || model.category === categoryValue;
    const matchesDeployment =
      deploymentValue === "Все варианты" || model.deployment === deploymentValue;

    return (
      matchesSearch && matchesFamily && matchesCategory && matchesDeployment
    );
  });
}

function updateCounters(filteredModels) {
  const resultsCount = document.getElementById("resultsCount");

  if (resultsCount) {
    resultsCount.textContent =
      filteredModels.length === models.length
        ? `Показаны все модели (${filteredModels.length})`
        : `Найдено моделей: ${filteredModels.length}`;
  }
}

function renderModels() {
  const list = document.getElementById("modelsList");
  const emptyState = document.getElementById("emptyState");

  if (!list) return;

  const filteredModels = filterModels();

  if (filteredModels.length === 0) {
    list.innerHTML = "";
    if (emptyState) emptyState.hidden = false;
    updateCounters(filteredModels);
    return;
  }

  if (emptyState) emptyState.hidden = true;
  list.innerHTML = filteredModels.map(createModelCard).join("");
  updateCounters(filteredModels);
}

function clearFilters() {
  const { searchInput, familySelect, categorySelect, deploymentSelect } =
    getControls();

  if (searchInput) searchInput.value = "";
  if (familySelect) familySelect.value = "Все семейства";
  if (categorySelect) categorySelect.value = "Все категории";
  if (deploymentSelect) deploymentSelect.value = "Все варианты";

  setActiveQuickFilter(null);
  renderModels();
}

function setActiveQuickFilter(activeButton) {
  const buttons = document.querySelectorAll(".quick-filter");
  buttons.forEach((button) => {
    button.classList.toggle("is-active", button === activeButton);
  });
}

function applyQuickPreset(key) {
  const preset = QUICK_PRESETS[key];
  if (!preset) return;

  const { searchInput, familySelect, categorySelect, deploymentSelect } =
    getControls();

  if (searchInput) searchInput.value = "";
  if (familySelect) familySelect.value = "Все семейства";
  if (categorySelect) categorySelect.value = "Все категории";
  if (deploymentSelect) deploymentSelect.value = "Все варианты";

  const filtered = models.filter(preset.filter);
  const list = document.getElementById("modelsList");
  const emptyState = document.getElementById("emptyState");

  if (!list) return;

  setActiveQuickFilter(
    document.querySelector(`.quick-filter[data-quick-filter="${key}"]`)
  );

  if (filtered.length === 0) {
    list.innerHTML = "";
    if (emptyState) emptyState.hidden = false;
    updateCounters(filtered);
    return;
  }

  if (emptyState) emptyState.hidden = true;
  list.innerHTML = filtered.map(createModelCard).join("");
  updateCounters(filtered);
}

function applyQuickSelection(button) {
  const { searchInput, familySelect, categorySelect, deploymentSelect } =
    getControls();

  if (searchInput) searchInput.value = button.dataset.quickSearch || "";
  if (familySelect) {
    familySelect.value = button.dataset.quickFamily || "Все семейства";
  }
  if (categorySelect) {
    categorySelect.value = button.dataset.quickCategory || "Все категории";
  }
  if (deploymentSelect) {
    deploymentSelect.value = button.dataset.quickDeployment || "Все варианты";
  }

  setActiveQuickFilter(button);
  renderModels();
  document.getElementById("catalog")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function initQuickFilters() {
  const buttons = document.querySelectorAll(".quick-filter");
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.quickFilter;

      if (key) {
        applyQuickPreset(key);
        return;
      }

      applyQuickSelection(button);
    });
  });

  const resetButton = document.getElementById("resetFilters");
  if (resetButton) {
    resetButton.addEventListener("click", clearFilters);
  }
}

function initControls() {
  const controls = ["search", "provider", "category", "deployment"];

  controls.forEach((id) => {
    const element = document.getElementById(id);
    if (!element) return;

    const handler = () => {
      setActiveQuickFilter(null);
      renderModels();
    };

    element.addEventListener("input", handler);
    element.addEventListener("change", handler);
  });
}

function populateProviderSelect() {
  const familySelect = document.getElementById("provider");
  if (!familySelect) return;

  const currentValue = familySelect.value;
  const families = [...new Set(models.map((model) => model.family))].sort();

  familySelect.innerHTML = `
    <option>Все семейства</option>
    ${families
      .map((family) => `<option>${escapeHtml(family)}</option>`)
      .join("")}
  `;

  if (families.includes(currentValue)) {
    familySelect.value = currentValue;
  } else {
    familySelect.value = "Все семейства";
  }
}

function initCatalog() {
  populateProviderSelect();
  initQuickFilters();
  initControls();
  renderModels();
}

document.addEventListener("DOMContentLoaded", initCatalog);
