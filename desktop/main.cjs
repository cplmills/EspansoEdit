const { app, BrowserWindow, Menu, Tray, dialog, ipcMain, nativeImage, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

const BACKEND_PORT = 8765;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const MAC_APP_PATH = ["/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"].join(":");

let mainWindow = null;
let backendProcess = null;
let tray = null;

const gotSingleInstanceLock = app.requestSingleInstanceLock();

if (!gotSingleInstanceLock) {
  app.quit();
}

function appRoot() {
  return app.getAppPath();
}

function backendDir() {
  return app.isPackaged ? path.join(process.resourcesPath, "backend") : path.join(appRoot(), "backend");
}

function frontendIndex() {
  return path.join(appRoot(), "frontend", "dist", "index.html");
}

function pythonCandidates() {
  const backend = backendDir();
  return [
    path.join(backend, ".venv", "bin", "python"),
    path.join(app.getAppPath(), "backend", ".venv", "bin", "python"),
    "python3"
  ];
}

function startBackend() {
  if (backendProcess) return;

  const cwd = backendDir();
  const python = pythonCandidates().find((candidate) => candidate === "python3" || fs.existsSync(candidate)) || "python3";
  backendProcess = spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)], {
    cwd,
    stdio: "pipe",
    env: { ...process.env, PATH: `${MAC_APP_PATH}:${process.env.PATH || ""}`, PYTHONPATH: cwd }
  });

  backendProcess.on("exit", () => {
    backendProcess = null;
  });
}

function waitForBackend(deadlineMs = 10000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      const request = http.get(`${BACKEND_URL}/api/status`, (response) => {
        response.resume();
        if (response.statusCode && response.statusCode < 500) {
          resolve();
          return;
        }
        retry();
      });
      request.on("error", retry);
      request.setTimeout(800, () => {
        request.destroy();
        retry();
      });
    };

    const retry = () => {
      if (Date.now() - started > deadlineMs) {
        reject(new Error("Backend did not start in time."));
        return;
      }
      setTimeout(check, 250);
    };

    check();
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 900,
    minHeight: 620,
    title: "EspansoEdit",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs")
    }
  });

  mainWindow.loadFile(frontendIndex());

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function showWindow() {
  if (!mainWindow) createWindow();
  mainWindow.show();
  mainWindow.focus();
}

function createTray() {
  const image = nativeImage.createFromDataURL(
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAQAAAC1+jfqAAAAKklEQVR4AWNgYGD4z0AEYBxVSFUBCjAyMhL+h2Ibgm0ItmGoGgAAg+gHH8mlQKMAAAAASUVORK5CYII="
  );
  image.setTemplateImage(true);
  tray = new Tray(image);
  tray.setToolTip("EspansoEdit");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Open EspansoEdit", click: showWindow },
      { label: "Open Espanso Match Folder", click: () => shell.openPath(path.join(app.getPath("home"), "Library", "Application Support", "espanso", "match")) },
      { type: "separator" },
      { label: "Quit", click: () => app.quit() }
    ])
  );
}

function createMenu() {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: "EspansoEdit",
        submenu: [
          { label: "Open EspansoEdit", click: showWindow },
          { type: "separator" },
          { role: "quit" }
        ]
      },
      {
        label: "Edit",
        submenu: [
          { role: "undo" },
          { role: "redo" },
          { type: "separator" },
          { role: "cut" },
          { role: "copy" },
          { role: "paste" },
          { role: "selectAll" }
        ]
      },
      {
        label: "View",
        submenu: [
          { role: "reload" },
          { role: "toggleDevTools" },
          { type: "separator" },
          { role: "resetZoom" },
          { role: "zoomIn" },
          { role: "zoomOut" }
        ]
      }
    ])
  );
}

ipcMain.handle("export:select-directory", async () => {
  const options = {
    title: "Choose Export Folder",
    properties: ["openDirectory", "createDirectory"]
  };
  const result = mainWindow ? await dialog.showOpenDialog(mainWindow, options) : await dialog.showOpenDialog(options);
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

if (gotSingleInstanceLock) {
  app.on("second-instance", showWindow);

  app.whenReady().then(async () => {
    createMenu();
    createTray();
    try {
      await waitForBackend(500);
    } catch (error) {
      startBackend();
      try {
        await waitForBackend();
      } catch (backendError) {
        console.error(backendError);
      }
    }
    createWindow();
  });

  app.on("activate", showWindow);

  app.on("before-quit", () => {
    if (backendProcess) backendProcess.kill();
  });
}
