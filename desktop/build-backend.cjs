const { spawnSync } = require("node:child_process");
const path = require("node:path");

const root = path.join(__dirname, "..");
const python = path.join(root, "backend", ".venv", "bin", "python");
const result = spawnSync(python, [
  "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
  "--name", "espansoedit-backend", "--target-arch", process.arch === "arm64" ? "arm64" : "x86_64",
  "--distpath", "backend/dist", "--workpath", "tmp/pyinstaller", "--specpath", "tmp/pyinstaller",
  "--paths", "backend", "--collect-submodules", "uvicorn", "--collect-data", "certifi",
  "backend/desktop_entry.py"
], { cwd: root, stdio: "inherit" });
if (result.error || result.status !== 0) {
  console.error("Backend packaging failed. Install backend/requirements-build.txt into backend/.venv first.");
  process.exit(result.status || 1);
}
