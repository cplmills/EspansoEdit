const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("espansoEdit", {
  request: (request) => ipcRenderer.invoke("backend:request", request),
  selectExportDirectory: () => ipcRenderer.invoke("export:select-directory")
});
