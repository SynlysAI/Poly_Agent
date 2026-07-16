/**
 * Independent literature-rag PM2 configuration.
 *
 * This process group is intended for a dedicated Poly_Agent knowledge
 * service instance, isolated from any shared literature-rag deployment.
 */
const fs = require("fs");
const path = require("path");

const SERVICE_ROOT = process.env.LITERATURE_RAG_PROJECT_ROOT || __dirname;
const ENV_FILE = path.join(SERVICE_ROOT, ".env");
const HOME = process.env.HOME || process.env.USERPROFILE || "";

function parseEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return {};

  const result = {};
  const content = fs.readFileSync(filePath, "utf8");
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;

    const index = line.indexOf("=");
    if (index < 0) continue;

    const key = line.slice(0, index).trim();
    let value = line.slice(index + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    result[key] = value;
  }
  return result;
}

function firstExistingPath(candidates) {
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  return "";
}

const fileEnv = parseEnvFile(ENV_FILE);
const mergedEnv = { ...fileEnv, ...process.env };
const condaEnv = mergedEnv.POLY_AGENT_CONDA_ENV || "poly_agent";
const pythonBin =
  mergedEnv.LITERATURE_RAG_PYTHON_BIN ||
  mergedEnv.POLY_AGENT_PYTHON_BIN ||
  firstExistingPath([
    path.join(HOME, "miniconda3", "envs", condaEnv, "bin", "python"),
    path.join(HOME, "miniconda3", "envs", condaEnv, "Scripts", "python.exe"),
    path.join(HOME, "anaconda3", "envs", condaEnv, "bin", "python"),
    path.join(HOME, "anaconda3", "envs", condaEnv, "Scripts", "python.exe"),
  ]);
if (!pythonBin) {
  throw new Error(
    "Unable to resolve a Python binary for literature-rag. Set LITERATURE_RAG_PYTHON_BIN or POLY_AGENT_PYTHON_BIN."
  );
}
const port = mergedEnv.LITERATURE_RAG_PORT || "8200";

const runtimeEnv = {
  ...process.env,
  ...fileEnv,
  PYTHONNOUSERSITE: "1",
};

module.exports = {
  apps: [
    {
      name: "literature-rag-api",
      cwd: SERVICE_ROOT,
      script: pythonBin,
      args: `-m uvicorn app.main:app --host 0.0.0.0 --port ${port}`,
      interpreter: "none",
      env: runtimeEnv,
      watch: false,
      autorestart: true,
      max_memory_restart: "2G",
    },
    {
      name: "literature-rag-worker",
      cwd: SERVICE_ROOT,
      script: pythonBin,
      args: "-m app.worker",
      interpreter: "none",
      env: runtimeEnv,
      watch: false,
      autorestart: true,
      max_memory_restart: "2G",
    },
  ],
};
