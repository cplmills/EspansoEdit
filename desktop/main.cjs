const { app, BrowserWindow, Menu, Tray, dialog, ipcMain, nativeImage, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");
const { requestBackend } = require("./backend-client.cjs");

let backendPort;
let backendUrl;
const MAC_APP_PATH = ["/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"].join(":");

let mainWindow = null;
let backendProcess = null;
let tray = null;
let backendFailure = null;
let backendReady = false;
let quitting = false;

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

function reserveBackendPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

function startBackend() {
  if (backendProcess) return;

  const cwd = backendDir();
  const executable = app.isPackaged
    ? path.join(cwd, "espansoedit-backend")
    : path.join(cwd, ".venv", "bin", "python");
  if (!fs.existsSync(executable)) throw new Error("The app's backend is missing. Please reinstall EspansoEdit.");
  const args = app.isPackaged ? ["--port", String(backendPort)] : ["desktop_entry.py", "--port", String(backendPort)];
  const frontend = app.isPackaged ? path.join(process.resourcesPath, "frontend") : path.join(appRoot(), "frontend", "dist");
  const logPath = path.join(app.getPath("userData"), "backend.log");
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  fs.writeFileSync(logPath, "");
  const env = { ...process.env, PATH: `${MAC_APP_PATH}:${process.env.PATH || ""}`, ESPANSOEDIT_FRONTEND_DIR: frontend };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  backendProcess = spawn(executable, args, {
    cwd,
    stdio: ["ignore", "pipe", "pipe"],
    env
  });
  for (const stream of [backendProcess.stdout, backendProcess.stderr]) {
    stream.on("data", (chunk) => fs.appendFileSync(logPath, chunk));
  }
  backendProcess.on("error", (error) => {
    backendFailure = error;
  });
  backendProcess.on("exit", (code, signal) => {
    backendProcess = null;
    backendFailure = new Error(`The backend stopped (${signal || `exit code ${code}`}).`);
    if (backendReady && !quitting) {
      dialog.showErrorBox("EspansoEdit backend stopped", `${backendFailure.message}\nPlease reopen the app.\n\nDiagnostic log: ${logPath}`);
      app.quit();
    }
  });
}

async function waitForBackend(deadlineMs = 45000) {
  const started = Date.now();
  while (Date.now() - started < deadlineMs) {
    if (backendFailure) throw backendFailure;
    const ready = await new Promise((resolve) => {
      const request = http.get(`${backendUrl}/`, (response) => {
        let body = "";
        response.on("data", (chunk) => { body += chunk; });
        response.on("error", () => resolve(false));
        response.on("end", () => {
          try {
            resolve(response.statusCode === 200 && JSON.parse(body).name === "Espanso Shortcut Manager");
          } catch { resolve(false); }
        });
      });
      request.on("error", () => resolve(false));
      request.setTimeout(800, () => {
        request.destroy();
        resolve(false);
      });
    });
    if (ready) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("The backend did not start in time.");
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 900,
    minHeight: 620,
    title: `EspansoEdit ${app.getVersion()}`,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs")
    }
  });

  mainWindow.loadURL(`${backendUrl}/ui/`);
  mainWindow.on("page-title-updated", (event) => event.preventDefault());

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function showWindow() {
  if (!backendReady) return;
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
          { role: "about", label: `About EspansoEdit ${app.getVersion()}` },
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
      },
      {
        role: "help",
        submenu: [{ label: "Show Diagnostic Log", click: () => shell.showItemInFolder(path.join(app.getPath("userData"), "backend.log")) }]
      }
    ])
  );
}

ipcMain.handle("backend:request", (event, request) => {
  if (!mainWindow || event.senderFrame !== mainWindow.webContents.mainFrame ||
      !event.senderFrame.url.startsWith(`${backendUrl}/ui/`)) {
    throw new Error("Requests are only available to the EspansoEdit window.");
  }
  return requestBackend(backendUrl, request, {
    app_version: app.getVersion(),
    backend_running: Boolean(backendProcess && !backendFailure),
    log_path: path.join(app.getPath("userData"), "backend.log")
  });
});

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
      backendPort = await reserveBackendPort();
      backendUrl = `http://127.0.0.1:${backendPort}`;
      startBackend();
      await waitForBackend();
      backendReady = true;
    } catch (error) {
      dialog.showErrorBox("EspansoEdit could not start", `${error.message}\n\nDiagnostic log: ${path.join(app.getPath("userData"), "backend.log")}\n\nPython does not need to be installed separately. Please reinstall the latest EspansoEdit build.`);
      app.quit();
      return;
    }
    createWindow();
  });

  app.on("activate", showWindow);

  app.on("before-quit", () => {
    quitting = true;
    if (backendProcess) backendProcess.kill();
  });
}
