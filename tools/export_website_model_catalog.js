#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const repoRoot = path.resolve(__dirname, "..");
const registryPath = path.join(repoRoot, "models", "catalog.json");
const websiteDataPath = path.join(repoRoot, "website", "models-data.js");

function readRegistry() {
  const raw = fs.readFileSync(registryPath, "utf8");
  const payload = JSON.parse(raw);

  if (!payload || !Array.isArray(payload.models)) {
    throw new Error("models/catalog.json must contain a top-level 'models' array");
  }

  return payload;
}

function validateModel(model, index) {
  const requiredStringFields = [
    "id",
    "display_name",
    "install_name",
    "family",
    "category",
    "deployment",
    "site_badge_text",
    "site_badge_class",
    "description",
    "install_command",
    "official_url",
    "ollama_url",
    "source_label",
    "note",
    "policy_tier",
    "support_tier",
  ];

  for (const field of requiredStringFields) {
    if (typeof model[field] !== "string" || !model[field].trim()) {
      throw new Error(`Model at index ${index} is missing required string field '${field}'`);
    }
  }

  const requiredArrayFields = [
    "server_requirements",
    "chips",
    "recommended_for",
    "input_types",
  ];

  for (const field of requiredArrayFields) {
    if (!Array.isArray(model[field])) {
      throw new Error(`Model '${model.id}' is missing required array field '${field}'`);
    }
  }
}

function exportWebsiteCatalog() {
  const payload = readRegistry();
  payload.models.forEach(validateModel);

  const websiteModels = payload.models.filter((model) => model.enabled_in_catalog !== false);
  const output = `// Generated from models/catalog.json by tools/export_website_model_catalog.js\nwindow.__MODEL_CATALOG__ = ${JSON.stringify(websiteModels, null, 2)};\n`;

  fs.writeFileSync(websiteDataPath, output, "utf8");
  console.log(`Exported ${websiteModels.length} models to website/models-data.js`);
}

exportWebsiteCatalog();
