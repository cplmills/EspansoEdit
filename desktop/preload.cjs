const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("espansoEdit", {
  selectExportDirectory: () => ipcRenderer.invoke("export:select-directory")
});
