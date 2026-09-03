import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";
import "./styles.css";

type View = "shortcuts" | "packages" | "settings" | "config" | "health" | "backups";
type ThemeMode = "dark" | "light";
type SyncMode = "none" | "one_way" | "two_way";
type BrowserSaveResult = "saved" | "cancelled" | "unsupported";
type BrowserDirectoryHandle = {
  getFileHandle: (name: string, options: { create: boolean }) => Promise<{
    createWritable: () => Promise<{
      write: (data: Blob | string) => Promise<void>;
      close: () => Promise<void>;
    }>;
  }>;
};

declare global {
  interface Window {
    espansoEdit?: {
      selectExportDirectory?: () => Promise<string | null>;
    };
    showDirectoryPicker?: (options?: { mode?: "read" | "readwrite" }) => Promise<BrowserDirectoryHandle>;
  }
}

type ApiError = {
  code: string;
  message: string;
  details?: unknown;
};

type Shortcut = {
  id: string;
  trigger: string | null;
  replace: string | null;
  form: string | null;
  form_fields: unknown;
  form_fields_yaml: string | null;
  label: string | null;
  word: boolean | null;
  propagate_case: boolean | null;
  case_insensitive: boolean | null;
  uppercase_style: string | null;
  force_mode: string | null;
  folder: string;
  file: string;
  path: string;
  editable: boolean;
  supported: boolean;
  kind: string;
  preview?: string | null;
  raw_yaml: string | null;
};

type Status = {
  installed: boolean;
  version: string | null;
  running: boolean;
  config_path: string | null;
  match_path: string | null;
  config_dir: string | null;
  executable: string | null;
  yaml_valid: boolean;
  duplicate_triggers: DuplicateTrigger[];
  last_reload: Record<string, unknown> | null;
};

type DuplicateTrigger = {
  trigger: string;
  files: string[];
  entries: { id: string; file: string; path: string; replace: string }[];
};

type Backup = {
  id: string;
  timestamp: string;
  original_path: string;
  backup_path: string;
  operation: string;
};

type BackupFrequency = "always" | "daily" | "manual";

type BackupSettings = {
  location: string | null;
  frequency: BackupFrequency;
  github_enabled: boolean;
  github_repo_url: string | null;
  github_access_token: string | null;
  github_branch: string | null;
  github_path: string;
  last_synced_at: string | null;
  last_sync_message: string | null;
};

type BackupClearResult = {
  success: boolean;
  removed_count: number;
};

type BackupSyncResult = {
  success: boolean;
  uploaded_count: number;
  repo: string | null;
  branch: string | null;
  backup_path: string | null;
  last_synced_at: string | null;
  message: string;
  settings: BackupSettings | null;
};

type BackupGitHubValidation = {
  success: boolean;
  exists: boolean;
  write_access: boolean;
  repo: string | null;
  branch: string | null;
  branches: string[];
  message: string;
};

type ConfigOptionType = "boolean" | "number" | "text" | "select" | "list";

type ConfigOption = {
  key: string;
  label: string;
  description: string;
  type: ConfigOptionType;
  category: string;
  default: unknown;
  choices: string[];
};

type ConfigValue = {
  key: string;
  enabled: boolean;
  value: unknown;
};

type ConfigPayload = {
  status: Status;
  default_path: string | null;
  options: ConfigOption[];
  values: Record<string, ConfigValue>;
  unknown_values: Record<string, unknown>;
  files: { path: string; file: string; content: string }[];
  reload: Record<string, unknown> | null;
};

type FolderExportResult = {
  success: boolean;
  folder: string;
  filename: string;
  content: string;
  shortcut_count: number;
  saved_path: string | null;
};

type FolderDeleteResult = {
  success: boolean;
  folder: string;
  deleted_path: string;
  removed_file_count: number;
  reload: Record<string, unknown> | null;
};

type GitSyncFile = {
  file_path: string;
  file_sha: string | null;
  shortcut_count: number;
};

type GitSyncSource = {
  id: string;
  name: string | null;
  enabled: boolean;
  repo_url: string | null;
  access_token: string | null;
  branch: string | null;
  folder: string;
  write_access: boolean;
  file_paths: string[];
  last_file_shas: Record<string, string>;
  last_local_hashes: Record<string, string>;
  installed_files: Record<string, string>;
  last_synced_at: string | null;
  last_sync_message: string | null;
};

type GitSyncSettings = {
  enabled: boolean;
  sources: GitSyncSource[];
};

type AppSettings = {
  theme: ThemeMode;
  git_sync: GitSyncSettings;
  backup: BackupSettings;
};

type GitSyncValidation = {
  success: boolean;
  source_id: string | null;
  exists: boolean;
  shortcut_file_found: boolean;
  write_access: boolean;
  repo: string | null;
  branch: string | null;
  branches: string[];
  file_path: string | null;
  file_sha: string | null;
  files: GitSyncFile[];
  shortcut_count: number;
  message: string;
};

type GitSyncResult = {
  success: boolean;
  changed: boolean;
  installed: boolean;
  uploaded: boolean;
  target_path: string | null;
  target_paths: string[];
  uploaded_paths: string[];
  validation: GitSyncValidation | null;
  validations: GitSyncValidation[];
  settings: AppSettings | null;
  reload: Record<string, unknown> | null;
};

type MutationResult = {
  success: boolean;
  reload: Record<string, unknown> | null;
  shortcut?: Shortcut | null;
};

type ShortcutFormValues = {
  matchType: "replace" | "form" | "yaml";
  trigger: string;
  replace: string;
  form: string;
  form_fields_yaml: string;
  label: string;
  word: boolean;
  propagate_case: boolean;
  case_insensitive: boolean;
  uppercase_style: string;
  force_mode: string;
  folder: string;
  raw_yaml: string;
  raw: boolean;
};

type FolderItem = {
  name: string;
  count: number;
};

type MacOSTextReplacementItem = {
  trigger: string;
  replacement: string;
  enabled: boolean;
};

type MacOSTextReplacementPreview = {
  success: boolean;
  available: boolean;
  macos_version: string | null;
  source_path: string | null;
  source_key: string | null;
  items: MacOSTextReplacementItem[];
  unsupported_count: number;
};

type MacOSTextReplacementSkip = {
  trigger: string | null;
  replacement: string | null;
  reason: string;
};

type MacOSTextReplacementImportResult = {
  success: boolean;
  source_path: string | null;
  total_found: number;
  imported_count: number;
  skipped_count: number;
  imported: Shortcut[];
  skipped: MacOSTextReplacementSkip[];
  reload: Record<string, unknown> | null;
};

type PackageItem = {
  name: string;
  path: string;
  file_count: number;
  shortcut_count: number;
  yaml_valid: boolean;
  version: string | null;
  description: string | null;
  source: string | null;
};

type PackageActionResult = {
  success: boolean;
  reload: Record<string, unknown> | null;
  command: string[];
  stdout: string;
  stderr: string;
  exit_code: number;
  package?: PackageItem | null;
};

type PackageInstallValues = {
  name: string;
  git: string;
  version: string;
  branch: string;
  external: boolean;
  force: boolean;
  refresh_index: boolean;
  use_native_git: boolean;
};

type FormFieldType = "text" | "multiline" | "choice" | "list";

type FormFieldDraft = {
  id: string;
  name: string;
  type: FormFieldType;
  values: string;
};

type ShortcutSortKey = "trigger" | "replacement" | "source" | "status";
type SortDirection = "asc" | "desc";
type ShortcutOptionPatch = {
  word?: boolean;
  propagate_case?: boolean;
  case_insensitive?: boolean;
};

const nav: { id: View; label: string }[] = [
  { id: "shortcuts", label: "Shortcuts" },
  { id: "packages", label: "Packages" },
  { id: "settings", label: "Settings" },
  { id: "config", label: "Config" },
  { id: "health", label: "Health" },
  { id: "backups", label: "Backups" }
];

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const apiBase = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "";
  const response = await fetch(`${apiBase}${path}`, {
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
    ...options
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail ?? payload;
    const error: ApiError = detail?.error ?? {
      code: "REQUEST_FAILED",
      message: response.statusText || "Request failed.",
      details: detail
    };
    throw error;
  }
  return payload as T;
}

function App() {
  const [view, setView] = useState<View>("shortcuts");
  const [shortcuts, setShortcuts] = useState<Shortcut[]>([]);
  const [folderNames, setFolderNames] = useState<string[]>(["Root"]);
  const [status, setStatus] = useState<Status | null>(null);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [packages, setPackages] = useState<PackageItem[]>([]);
  const [config, setConfig] = useState<ConfigPayload | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [search, setSearch] = useState("");
  const [selectedFolder, setSelectedFolder] = useState("All");
  const [editing, setEditing] = useState<Shortcut | "new" | null>(null);
  const [moving, setMoving] = useState<Shortcut | null>(null);
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [importingMacOS, setImportingMacOS] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [navigationCollapsed, setNavigationCollapsed] = useState(false);
  const [foldersCollapsed, setFoldersCollapsed] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextStatus, nextShortcuts, nextFolders, nextSettings] = await Promise.all([
        api<Status>("/api/status"),
        api<Shortcut[]>("/api/shortcuts"),
        api<string[]>("/api/folders"),
        api<AppSettings>("/api/settings")
      ]);
      setStatus(nextStatus);
      setShortcuts(nextShortcuts);
      setFolderNames(nextFolders);
      setSettings(normalizeAppSettings(nextSettings));
      if (view === "backups") setBackups(await api<Backup[]>("/api/backups"));
      if (view === "packages") setPackages(await api<PackageItem[]>("/api/packages"));
      if (view === "config") setConfig(await api<ConfigPayload>("/api/config"));
    } catch (err) {
      setError(normalizeError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = settings?.theme ?? "dark";
  }, [settings?.theme]);

  useEffect(() => {
    if (!notice && !error) return;
    const timer = window.setTimeout(() => {
      setNotice("");
      setError(null);
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [notice, error]);

  useEffect(() => {
    if (view === "backups") {
      api<Backup[]>("/api/backups").then(setBackups).catch((err) => setError(normalizeError(err)));
    }
    if (view === "config") {
      api<ConfigPayload>("/api/config").then(setConfig).catch((err) => setError(normalizeError(err)));
    }
    if (view === "packages") {
      api<PackageItem[]>("/api/packages").then(setPackages).catch((err) => setError(normalizeError(err)));
    }
    if (view === "settings") {
      api<AppSettings>("/api/settings").then((nextSettings) => setSettings(normalizeAppSettings(nextSettings))).catch((err) => setError(normalizeError(err)));
    }
  }, [view]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return shortcuts.filter((shortcut) => {
      const folderMatch = selectedFolder === "All" || shortcut.folder === selectedFolder;
      const searchMatch = !term || [shortcut.trigger, shortcut.replace, shortcut.form, shortcut.label, shortcut.file, shortcut.folder].some((value) => value?.toLowerCase().includes(term));
      return folderMatch && searchMatch;
    });
  }, [search, selectedFolder, shortcuts]);

  const folders = useMemo<FolderItem[]>(() => {
    const counts = new Map<string, number>();
    for (const shortcut of shortcuts) counts.set(shortcut.folder, (counts.get(shortcut.folder) ?? 0) + 1);
    const names = new Set([...folderNames, ...counts.keys(), "Root"]);
    return [...names].sort((a, b) => (a === "Root" ? -1 : b === "Root" ? 1 : a.localeCompare(b))).map((name) => ({
      name,
      count: counts.get(name) ?? 0
    }));
  }, [folderNames, shortcuts]);

  const saveShortcut = async (values: ShortcutFormValues) => {
    setNotice("");
    setError(null);
    try {
      if (editing === "new") {
        const result = values.raw
          ? await api<MutationResult>("/api/shortcuts/raw", { method: "POST", body: JSON.stringify({ yaml: values.raw_yaml, folder: values.folder }) })
          : await api<MutationResult>("/api/shortcuts", { method: "POST", body: JSON.stringify(toStructuredPayload(values)) });
        setNotice(`Shortcut added. ${reloadMessage(result.reload)}`);
      } else if (editing) {
        const path = values.raw ? `/api/shortcuts/${editing.id}/raw` : `/api/shortcuts/${editing.id}`;
        const body = values.raw ? { yaml: values.raw_yaml } : toStructuredPayload(values);
        const result = await api<MutationResult>(path, { method: "PUT", body: JSON.stringify(body) });
        setNotice(`Shortcut updated. ${reloadMessage(result.reload)}`);
      }
      setEditing(null);
      await refresh();
    } catch (err) {
      setError(normalizeError(err));
    }
  };

  const moveShortcut = async (shortcut: Shortcut, folder: string) => {
    setNotice("");
    setError(null);
    try {
      const result = await api<MutationResult>(`/api/shortcuts/${shortcut.id}/move`, {
        method: "PUT",
        body: JSON.stringify({ folder })
      });
      setNotice(`Shortcut moved. ${reloadMessage(result.reload)}`);
      setMoving(null);
      await refresh();
    } catch (err) {
      setError(normalizeError(err));
    }
  };

  const createFolder = async (folder: string) => {
    setNotice("");
    setError(null);
    try {
      const result = await api<{ folder: string }>("/api/folders", {
        method: "POST",
        body: JSON.stringify({ folder })
      });
      setNotice(`Folder created: ${result.folder}`);
      setSelectedFolder(result.folder);
      setCreatingFolder(false);
      await refresh();
    } catch (err) {
      setError(normalizeError(err));
    }
  };

  const deleteFolder = async (folder: string) => {
    const syncedSources = enabledSyncSourcesForFolder(settings, folder);
    if (syncedSources.length > 0) {
      const openSettings = window.confirm("This folder is managed by GitHub sync. Disable the sync source before deleting it. Open Settings now?");
      if (openSettings) setView("settings");
      return;
    }
    if (!window.confirm(`Delete folder ${folder} and all shortcuts inside it?`)) return;
    setNotice("");
    setError(null);
    try {
      const result = await api<FolderDeleteResult>(`/api/folders/${encodeFolderPath(folder)}`, { method: "DELETE" });
      if (selectedFolder === folder) setSelectedFolder("All");
      setNotice(`Deleted ${result.folder}. Removed ${result.removed_file_count} file${result.removed_file_count === 1 ? "" : "s"}. ${reloadMessage(result.reload)}`);
      await refresh();
    } catch (err) {
      const normalized = normalizeError(err);
      if (normalized.code === "FOLDER_SYNC_ENABLED") {
        const openSettings = window.confirm(`${normalized.message} Open Settings now?`);
        if (openSettings) setView("settings");
        return;
      }
      setError(normalized);
    }
  };

  const exportFolder = async (folder: string) => {
    if (folder === "All") {
      setError({ code: "FOLDER_REQUIRED", message: "Select a folder before exporting." });
      return;
    }
    setNotice("");
    setError(null);
    try {
      const destinationFolder = await window.espansoEdit?.selectExportDirectory?.();
      if (window.espansoEdit?.selectExportDirectory && !destinationFolder) return;
      const result = await api<FolderExportResult>("/api/folders/export", {
        method: "POST",
        body: JSON.stringify({ folder, destination_folder: destinationFolder })
      });
      if (result.saved_path) {
        setNotice(`Saved ${result.shortcut_count} shortcut${result.shortcut_count === 1 ? "" : "s"} from ${result.folder} to ${result.saved_path}.`);
      } else {
        const browserSave = await saveTextFileWithBrowserPicker(result.filename, result.content, "application/x-yaml;charset=utf-8");
        if (browserSave === "cancelled") return;
        if (browserSave === "saved") {
          setNotice(`Saved ${result.shortcut_count} shortcut${result.shortcut_count === 1 ? "" : "s"} from ${result.folder}.`);
        } else {
          downloadTextFile(result.filename, result.content, "application/x-yaml;charset=utf-8");
          setNotice(`Exported ${result.shortcut_count} shortcut${result.shortcut_count === 1 ? "" : "s"} from ${result.folder}.`);
        }
      }
    } catch (err) {
      setError(normalizeError(err));
    }
  };

  const importMacOSReplacements = async (folder: string, replacements: MacOSTextReplacementItem[]) => {
    setNotice("");
    setError(null);
    try {
      const result = await api<MacOSTextReplacementImportResult>("/api/import/macos-text-replacements", {
        method: "POST",
        body: JSON.stringify({ folder, replacements })
      });
      const reloadText = result.imported_count > 0 ? ` ${reloadMessage(result.reload)}` : "";
      setNotice(`Imported ${result.imported_count} macOS replacements. Skipped ${result.skipped_count}.${reloadText}`);
      setImportingMacOS(false);
      await refresh();
      return result;
    } catch (err) {
      setError(normalizeError(err));
      throw err;
    }
  };

  const dropShortcut = async (shortcutId: string, folder: string) => {
    const shortcut = shortcuts.find((item) => item.id === shortcutId);
    if (!shortcut || shortcut.folder === folder) return;
    await moveShortcut(shortcut, folder);
  };

  const deleteShortcut = async (shortcut: Shortcut) => {
    if (!shortcut.trigger || !window.confirm(`Delete shortcut ${shortcut.trigger}?`)) return;
    setNotice("");
    setError(null);
    try {
      const result = await api<MutationResult>(`/api/shortcuts/${shortcut.id}`, { method: "DELETE" });
      setNotice(`Shortcut deleted. ${reloadMessage(result.reload)}`);
      await refresh();
    } catch (err) {
      setError(normalizeError(err));
    }
  };

  const bulkUpdateShortcutOptions = async (selectedShortcuts: Shortcut[], patch: ShortcutOptionPatch) => {
    const editableShortcuts = selectedShortcuts.filter((shortcut) => shortcut.editable && shortcut.supported && shortcut.trigger);
    if (editableShortcuts.length === 0) return;
    setNotice("");
    setError(null);
    try {
      let reload: Record<string, unknown> | null = null;
      for (const shortcut of editableShortcuts) {
        const result = await api<MutationResult>(`/api/shortcuts/${shortcut.id}`, {
          method: "PUT",
          body: JSON.stringify(toShortcutUpdatePayload(shortcut, patch))
        });
        reload = result.reload;
      }
      setNotice(`Updated ${editableShortcuts.length} shortcut${editableShortcuts.length === 1 ? "" : "s"}. ${reloadMessage(reload)}`);
      await refresh();
    } catch (err) {
      setError(normalizeError(err));
      throw err;
    }
  };

  const runValidation = async () => {
    setError(null);
    try {
      await api("/api/validate", { method: "POST" });
      setNotice("Validation completed.");
      await refresh();
    } catch (err) {
      setError(normalizeError(err));
    }
  };

  const restore = async (backup: Backup) => {
    if (!window.confirm(`Restore backup from ${backup.timestamp}?`)) return;
    setError(null);
    try {
      const result = await api<MutationResult>(`/api/backups/${backup.id}/restore`, { method: "POST" });
      setNotice(`Backup restored. ${reloadMessage(result.reload)}`);
      await refresh();
      setBackups(await api<Backup[]>("/api/backups"));
    } catch (err) {
      setError(normalizeError(err));
    }
  };

  const saveBackupSettings = async (backupSettings: BackupSettings) => {
    setNotice("");
    setError(null);
    try {
      const updated = await api<BackupSettings>("/api/backups/settings", {
        method: "PUT",
        body: JSON.stringify(normalizeBackupSettings(backupSettings))
      });
      setSettings((current) => current ? { ...current, backup: updated } : current);
      setNotice("Backup settings saved.");
      await refresh();
      return updated;
    } catch (err) {
      setError(normalizeError(err));
      throw err;
    }
  };

  const moveBackupLocation = async () => {
    const destinationFolder = await window.espansoEdit?.selectExportDirectory?.();
    if (window.espansoEdit?.selectExportDirectory && !destinationFolder) return;
    const manualPath = destinationFolder ?? window.prompt("Backup folder path");
    if (!manualPath) return;
    setNotice("");
    setError(null);
    try {
      const updated = await api<BackupSettings>("/api/backups/move", {
        method: "POST",
        body: JSON.stringify({ location: manualPath })
      });
      setSettings((current) => current ? { ...current, backup: updated } : current);
      setNotice(`Backup location moved to ${updated.location}.`);
      await refresh();
      setBackups(await api<Backup[]>("/api/backups"));
      return updated;
    } catch (err) {
      setError(normalizeError(err));
      throw err;
    }
  };

  const clearBackups = async () => {
    if (!window.confirm("Clear all backups? This cannot be undone.")) return;
    setNotice("");
    setError(null);
    try {
      const result = await api<BackupClearResult>("/api/backups/clear", { method: "POST" });
      setNotice(`Cleared ${result.removed_count} backup${result.removed_count === 1 ? "" : "s"}.`);
      setBackups(await api<Backup[]>("/api/backups"));
      await refresh();
    } catch (err) {
      setError(normalizeError(err));
    }
  };

  const syncBackups = async () => {
    setNotice("");
    setError(null);
    try {
      const result = await api<BackupSyncResult>("/api/backups/sync", { method: "POST" });
      if (result.settings) setSettings((current) => current ? { ...current, backup: result.settings! } : current);
      setNotice(result.message || `Uploaded ${result.uploaded_count} backup file${result.uploaded_count === 1 ? "" : "s"} to GitHub.`);
      await refresh();
      return result;
    } catch (err) {
      setError(normalizeError(err));
      throw err;
    }
  };

  const validateBackupGitHub = async (backupSettings: BackupSettings) => {
    setError(null);
    try {
      return await api<BackupGitHubValidation>("/api/backups/github/validate", {
        method: "POST",
        body: JSON.stringify(normalizeBackupSettings(backupSettings))
      });
    } catch (err) {
      setError(normalizeError(err));
      throw err;
    }
  };

  const installPackage = async (values: PackageInstallValues) => {
    setNotice("");
    setError(null);
    try {
      const result = await api<PackageActionResult>("/api/packages", { method: "POST", body: JSON.stringify(values) });
      setNotice(`Package installed. ${reloadMessage(result.reload)}`);
      setPackages(await api<PackageItem[]>("/api/packages"));
      await refresh();
    } catch (err) {
      setError(normalizeError(err));
    }
  };

  const updatePackage = async (packageName: string) => {
    setNotice("");
    setError(null);
    try {
      const result = await api<PackageActionResult>(`/api/packages/${encodeURIComponent(packageName)}/update`, { method: "POST" });
      setNotice(`Package updated. ${reloadMessage(result.reload)}`);
      setPackages(await api<PackageItem[]>("/api/packages"));
      await refresh();
    } catch (err) {
      setError(normalizeError(err));
    }
  };

  const removePackage = async (packageName: string) => {
    if (!window.confirm(`Remove package ${packageName}?`)) return;
    setNotice("");
    setError(null);
    try {
      const result = await api<PackageActionResult>(`/api/packages/${encodeURIComponent(packageName)}`, { method: "DELETE" });
      setNotice(`Package removed. ${reloadMessage(result.reload)}`);
      setPackages(await api<PackageItem[]>("/api/packages"));
      await refresh();
    } catch (err) {
      setError(normalizeError(err));
    }
  };

  const saveSettings = async (nextSettings: AppSettings) => {
    setNotice("");
    setError(null);
    try {
      const updated = await api<AppSettings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(normalizeAppSettings(nextSettings))
      });
      setSettings(normalizeAppSettings(updated));
      setNotice("Settings saved.");
      await refresh();
      return updated;
    } catch (err) {
      setError(normalizeError(err));
      throw err;
    }
  };

  const saveConfig = async (values: ConfigValue[]) => {
    setNotice("");
    setError(null);
    try {
      const updated = await api<ConfigPayload>("/api/config", {
        method: "PUT",
        body: JSON.stringify({ values })
      });
      setConfig(updated);
      setNotice(`Espanso config saved. ${reloadMessage(updated.reload)}`);
      await refresh();
      return updated;
    } catch (err) {
      setError(normalizeError(err));
      throw err;
    }
  };

  const validateGitSyncSettings = async (source: GitSyncSource) => {
    setError(null);
    try {
      return await api<GitSyncValidation>("/api/settings/git-sync/validate", {
        method: "POST",
        body: JSON.stringify(source)
      });
    } catch (err) {
      setError(normalizeError(err));
      throw err;
    }
  };

  const syncGitShortcuts = async () => {
    setNotice("");
    setError(null);
    try {
      const result = await api<GitSyncResult>("/api/settings/git-sync/sync", { method: "POST" });
      if (result.settings) setSettings(normalizeAppSettings(result.settings));
      const actions = [
        result.installed ? `installed ${result.target_paths.length} file${result.target_paths.length === 1 ? "" : "s"}` : "",
        result.uploaded ? `uploaded ${result.uploaded_paths.length} file${result.uploaded_paths.length === 1 ? "" : "s"}` : "",
      ].filter(Boolean);
      const action = actions.length > 0 ? actions.join(" and ") : "already up to date";
      setNotice(`GitHub shortcuts ${action}.${result.reload ? ` ${reloadMessage(result.reload)}` : ""}`);
      await refresh();
      return result;
    } catch (err) {
      setError(normalizeError(err));
      throw err;
    }
  };

  const disableGitSyncSource = async (source: GitSyncSource, removeShortcuts: boolean) => {
    setNotice("");
    setError(null);
    try {
      const result = await api<GitSyncResult>(`/api/settings/git-sync/sources/${encodeURIComponent(source.id)}/disable`, {
        method: "POST",
        body: JSON.stringify({ remove_shortcuts: removeShortcuts })
      });
      if (result.settings) setSettings(normalizeAppSettings(result.settings));
      const cleanup = removeShortcuts ? ` Removed ${result.target_paths.length} synced file${result.target_paths.length === 1 ? "" : "s"}.` : " Installed shortcuts were kept.";
      setNotice(`GitHub sync disabled for ${source.repo_url ?? "repository"}.${cleanup}${result.reload ? ` ${reloadMessage(result.reload)}` : ""}`);
      await refresh();
      return result;
    } catch (err) {
      setError(normalizeError(err));
      throw err;
    }
  };

  useEffect(() => {
    let active = true;
    api<GitSyncResult>("/api/settings/git-sync/sync", { method: "POST" })
      .then(async (result) => {
        if (!active) return;
        if (result.settings) setSettings(normalizeAppSettings(result.settings));
        if (result.installed) {
          setNotice(`GitHub shortcuts installed ${result.target_paths.length} file${result.target_paths.length === 1 ? "" : "s"}. ${result.reload ? reloadMessage(result.reload) : ""}`);
          await refresh();
        }
      })
      .catch((err) => {
        if (active) setError(normalizeError(err));
      });
    return () => {
      active = false;
    };
  }, []);

  const alertStack = createPortal(
    <div className="statusOverlay" aria-live="polite">
      {loading && <div className="loading">Loading...</div>}
      {error && <Alert type="error" title={error.code} message={error.message} details={error.details} onClose={() => setError(null)} />}
      {notice && <Alert type="success" title="Success" message={notice} onClose={() => setNotice("")} />}
    </div>,
    document.body,
  );

  return (
    <>
      {alertStack}
      <div className={`shell ${sidebarCollapsed ? "sidebarCollapsed" : ""}`}>
      <aside className="sidebar">
        <button
          className="sidebarToggle"
          type="button"
          aria-label={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
          onClick={() => setSidebarCollapsed((value) => !value)}
        >
          {sidebarCollapsed ? ">" : "<"}
        </button>
        {!sidebarCollapsed && (
          <>
            <div className="brand">Espanso Shortcut Manager</div>
            <SidebarSection title="Navigation" collapsed={navigationCollapsed} onToggle={() => setNavigationCollapsed((value) => !value)}>
              <nav>
                {nav.map((item) => (
                  <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}>
                    {item.label}
                  </button>
                ))}
              </nav>
            </SidebarSection>
            {view === "shortcuts" && (
              <FolderRail
                folders={folders}
                selectedFolder={selectedFolder}
                collapsed={foldersCollapsed}
                onToggle={() => setFoldersCollapsed((value) => !value)}
                onSelect={setSelectedFolder}
                onDropShortcut={dropShortcut}
                onDeleteFolder={deleteFolder}
                syncModeForFolder={(folder) => syncModeForFolder(settings, folder)}
              />
            )}
          </>
        )}
      </aside>
      <main className="content">
        {view === "shortcuts" && (
          <ShortcutsView
            shortcuts={filtered}
            search={search}
            setSearch={setSearch}
            onAdd={() => setEditing("new")}
            onImportMacOS={() => setImportingMacOS(true)}
            onCreateFolder={() => setCreatingFolder(true)}
            selectedFolder={selectedFolder}
            onExportFolder={exportFolder}
            onEdit={setEditing}
            onMove={setMoving}
            onDelete={deleteShortcut}
            onBulkUpdateOptions={bulkUpdateShortcutOptions}
          />
        )}
        {view === "health" && <HealthView status={status} onValidate={runValidation} />}
        {view === "backups" && (
          <BackupsView
            backups={backups}
            settings={settings?.backup ?? defaultBackupSettings()}
            onRestore={restore}
            onSaveSettings={saveBackupSettings}
            onMoveLocation={moveBackupLocation}
            onClear={clearBackups}
            onSync={syncBackups}
            onValidateGitHub={validateBackupGitHub}
          />
        )}
        {view === "packages" && <PackagesView packages={packages} onInstall={installPackage} onUpdate={updatePackage} onRemove={removePackage} />}
        {view === "settings" && (
          <SettingsView
            settings={settings}
            folders={folders}
            onSave={saveSettings}
            onValidateGitSync={validateGitSyncSettings}
            onSyncGit={syncGitShortcuts}
            onDisableGitSyncSource={disableGitSyncSource}
          />
        )}
        {view === "config" && <ConfigView config={config} onSave={saveConfig} />}
      </main>
      {editing && (
        <ShortcutDialog
          shortcut={editing === "new" ? null : editing}
          folders={folders}
          initialFolder={editing === "new" && selectedFolder !== "All" ? selectedFolder : "Root"}
          onClose={() => setEditing(null)}
          onSave={saveShortcut}
        />
      )}
      {moving && (
        <MoveDialog
          shortcut={moving}
          folders={folders}
          onClose={() => setMoving(null)}
          onMove={(folder) => moveShortcut(moving, folder)}
        />
      )}
      {creatingFolder && (
        <FolderDialog
          folders={folders}
          onClose={() => setCreatingFolder(false)}
          onCreate={createFolder}
        />
      )}
      {importingMacOS && (
        <MacOSImportDialog
          folders={folders}
          initialFolder={selectedFolder !== "All" ? selectedFolder : "Root"}
          onClose={() => setImportingMacOS(false)}
          onImport={importMacOSReplacements}
        />
      )}
      </div>
    </>
  );
}

function ShortcutsView(props: {
  shortcuts: Shortcut[];
  search: string;
  setSearch: (value: string) => void;
  onAdd: () => void;
  onImportMacOS: () => void;
  onCreateFolder: () => void;
  selectedFolder: string;
  onExportFolder: (folder: string) => void;
  onEdit: (shortcut: Shortcut) => void;
  onMove: (shortcut: Shortcut) => void;
  onDelete: (shortcut: Shortcut) => void;
  onBulkUpdateOptions: (shortcuts: Shortcut[], patch: ShortcutOptionPatch) => Promise<void>;
}) {
  const [sortKey, setSortKey] = useState<ShortcutSortKey>("trigger");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkSaving, setBulkSaving] = useState(false);

  const sortedShortcuts = useMemo(() => sortShortcuts(props.shortcuts, sortKey, sortDirection), [props.shortcuts, sortDirection, sortKey]);
  const selectableShortcuts = sortedShortcuts.filter(isBulkEditableShortcut);
  const selectedShortcuts = sortedShortcuts.filter((shortcut) => selectedIds.has(shortcut.id));
  const allVisibleSelected = selectableShortcuts.length > 0 && selectableShortcuts.every((shortcut) => selectedIds.has(shortcut.id));

  useEffect(() => {
    const visibleIds = new Set(props.shortcuts.map((shortcut) => shortcut.id));
    setSelectedIds((current) => new Set([...current].filter((id) => visibleIds.has(id))));
  }, [props.shortcuts]);

  const changeSort = (key: ShortcutSortKey) => {
    if (sortKey === key) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  };

  const toggleShortcut = (shortcut: Shortcut, checked: boolean) => {
    if (!isBulkEditableShortcut(shortcut)) return;
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(shortcut.id);
      } else {
        next.delete(shortcut.id);
      }
      return next;
    });
  };

  const toggleAllVisible = (checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const shortcut of selectableShortcuts) {
        if (checked) {
          next.add(shortcut.id);
        } else {
          next.delete(shortcut.id);
        }
      }
      return next;
    });
  };

  const applyBulkPatch = async (patch: ShortcutOptionPatch) => {
    if (selectedShortcuts.length === 0) return;
    setBulkSaving(true);
    try {
      await props.onBulkUpdateOptions(selectedShortcuts, patch);
      setSelectedIds(new Set());
    } finally {
      setBulkSaving(false);
    }
  };

  return (
    <section>
      <div className="toolbar">
        <h1>Shortcuts</h1>
        <div className="toolbarActions">
          <IconButton label="Import from macOS" disabled={false} onClick={props.onImportMacOS} icon={<ImportIcon />} />
          <IconButton label="New Folder" disabled={false} onClick={props.onCreateFolder} icon={<FolderPlusIcon />} />
          <IconButton label="Export Folder" disabled={props.selectedFolder === "All"} onClick={() => props.onExportFolder(props.selectedFolder)} icon={<ExportIcon />} />
          <IconButton label="Add Shortcut" className="primary" disabled={false} onClick={props.onAdd} icon={<PlusIcon />} />
        </div>
      </div>
      <input
        className="search"
        placeholder="Search trigger, replacement, or file"
        value={props.search}
        onChange={(event) => props.setSearch(event.target.value)}
      />
      {selectedShortcuts.length > 0 && (
        <div className="bulkBar">
          <strong>{selectedShortcuts.length} selected</strong>
          <div className="bulkActions">
            <button disabled={bulkSaving} onClick={() => applyBulkPatch({ word: true })}>Enable Word Trigger</button>
            <button disabled={bulkSaving} onClick={() => applyBulkPatch({ word: false })}>Disable Word Trigger</button>
            <button disabled={bulkSaving} onClick={() => applyBulkPatch({ propagate_case: true })}>Enable Propagate Case</button>
            <button disabled={bulkSaving} onClick={() => applyBulkPatch({ propagate_case: false })}>Disable Propagate Case</button>
            <button disabled={bulkSaving} onClick={() => applyBulkPatch({ case_insensitive: true })}>Enable Case-insensitive</button>
            <button disabled={bulkSaving} onClick={() => applyBulkPatch({ case_insensitive: false })}>Disable Case-insensitive</button>
            <button disabled={bulkSaving} onClick={() => setSelectedIds(new Set())}>Clear</button>
          </div>
        </div>
      )}
      <div className="table">
        <div className="row header shortcutRow">
          <span>
            <input
              aria-label="Select all visible editable shortcuts"
              checked={allVisibleSelected}
              disabled={selectableShortcuts.length === 0}
              type="checkbox"
              onChange={(event) => toggleAllVisible(event.target.checked)}
            />
          </span>
          <SortableHeader label="Trigger" column="trigger" sortKey={sortKey} sortDirection={sortDirection} onSort={changeSort} />
          <SortableHeader label="Replacement" column="replacement" sortKey={sortKey} sortDirection={sortDirection} onSort={changeSort} />
          <SortableHeader label="Source" column="source" sortKey={sortKey} sortDirection={sortDirection} onSort={changeSort} />
          <SortableHeader label="Status" column="status" sortKey={sortKey} sortDirection={sortDirection} onSort={changeSort} />
          <span></span>
        </div>
        {sortedShortcuts.map((shortcut) => (
          <div
            className="row shortcutRow"
            key={shortcut.id}
            draggable={Boolean(shortcut.raw_yaml)}
            onDragStart={(event) => {
              event.dataTransfer.setData("text/plain", shortcut.id);
              event.dataTransfer.effectAllowed = "move";
            }}
          >
            <span>
              <input
                aria-label={`Select ${shortcut.trigger ?? "shortcut"}`}
                checked={selectedIds.has(shortcut.id)}
                disabled={!isBulkEditableShortcut(shortcut)}
                type="checkbox"
                onChange={(event) => toggleShortcut(shortcut, event.target.checked)}
              />
            </span>
            <strong className="triggerText">{shortcut.trigger ?? "Advanced entry"}</strong>
            <span className="preview">{shortcut.replace ?? shortcut.form ?? "Unsupported match type"}</span>
            <span>{sourceLabel(shortcut)}</span>
            <StatusPill ok={shortcut.supported} label={shortcut.form ? "Form" : shortcut.supported ? "Structured" : "YAML"} />
            <span className="actions">
              <IconButton label="Edit" disabled={!shortcut.editable && !shortcut.raw_yaml} onClick={() => props.onEdit(shortcut)} icon={<PencilIcon />} />
              <IconButton label="Move" disabled={!shortcut.raw_yaml} onClick={() => props.onMove(shortcut)} icon={<MoveIcon />} />
              <IconButton label="Delete" disabled={!shortcut.editable} onClick={() => props.onDelete(shortcut)} icon={<TrashIcon />} />
            </span>
          </div>
        ))}
        {props.shortcuts.length === 0 && <div className="empty">No shortcuts found.</div>}
      </div>
    </section>
  );
}

function SortableHeader(props: {
  label: string;
  column: ShortcutSortKey;
  sortKey: ShortcutSortKey;
  sortDirection: SortDirection;
  onSort: (column: ShortcutSortKey) => void;
}) {
  const active = props.sortKey === props.column;
  return (
    <button
      className={`sortHeader ${active ? "activeSort" : ""}`}
      type="button"
      aria-sort={active ? (props.sortDirection === "asc" ? "ascending" : "descending") : "none"}
      onClick={() => props.onSort(props.column)}
    >
      <span>{props.label}</span>
      <span className="sortIndicator">{active ? (props.sortDirection === "asc" ? "^" : "v") : ""}</span>
    </button>
  );
}

function IconButton(props: { label: string; className?: string; disabled: boolean; icon: React.ReactNode; onClick: () => void }) {
  const className = ["iconButton", props.className].filter(Boolean).join(" ");
  return (
    <button className={className} type="button" aria-label={props.label} title={props.label} disabled={props.disabled} onClick={props.onClick}>
      {props.icon}
    </button>
  );
}

function ImportIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3v12" />
      <path d="m7 10 5 5 5-5" />
      <path d="M4 17v3h16v-3" />
    </svg>
  );
}

function FolderPlusIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 6h7l2 3h9v10H3V6Z" />
      <path d="M12 14h6" />
      <path d="M15 11v6" />
    </svg>
  );
}

function ExportIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 15V3" />
      <path d="m7 8 5-5 5 5" />
      <path d="M5 14v6h14v-6" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
  );
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 20h4l11-11-4-4L4 16v4Z" />
      <path d="m14 6 4 4" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7h16" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M6 7l1 13h10l1-13" />
      <path d="M9 7V4h6v3" />
    </svg>
  );
}

function MoveIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2v20" />
      <path d="m8 6 4-4 4 4" />
      <path d="m8 18 4 4 4-4" />
      <path d="M2 12h20" />
      <path d="m6 8-4 4 4 4" />
      <path d="m18 8 4 4-4 4" />
    </svg>
  );
}

function FolderRail(props: {
  folders: FolderItem[];
  selectedFolder: string;
  collapsed: boolean;
  onToggle: () => void;
  onSelect: (folder: string) => void;
  onDropShortcut: (shortcutId: string, folder: string) => void;
  onDeleteFolder: (folder: string) => void;
  syncModeForFolder: (folder: string) => SyncMode;
}) {
  const totalCount = props.folders.reduce((sum, folder) => sum + folder.count, 0);

  const dropOnFolder = (event: React.DragEvent<HTMLDivElement>, folder: string) => {
    event.preventDefault();
    const shortcutId = event.dataTransfer.getData("text/plain");
    if (shortcutId) props.onDropShortcut(shortcutId, folder);
  };

  return (
    <SidebarSection title="Folders" collapsed={props.collapsed} onToggle={props.onToggle}>
      <div className="folderRail">
        <button className={props.selectedFolder === "All" ? "active" : ""} onClick={() => props.onSelect("All")}>
          <span>All</span>
          <strong>{totalCount}</strong>
        </button>
        {props.folders.map((folder) => {
          const syncMode = props.syncModeForFolder(folder.name);
          const isSynced = syncMode !== "none";
          return (
            <div
              key={folder.name}
              className={`folderRailItem ${props.selectedFolder === folder.name ? "active" : ""}`}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => dropOnFolder(event, folder.name)}
            >
              <button className="folderSelect" onClick={() => props.onSelect(folder.name)}>
                <span className="folderNameWithSync">
                  <span className="folderNameText">{folder.name}</span>
                  {isSynced && (
                    <span
                      className={`folderSyncIcon ${syncMode}`}
                      title={syncMode === "two_way" ? "Two-way GitHub sync" : "One-way GitHub sync"}
                      aria-label={syncMode === "two_way" ? "Two-way GitHub sync" : "One-way GitHub sync"}
                    >
                      {syncMode === "two_way" ? "⇆" : "↓"}
                    </span>
                  )}
                </span>
                <strong>{folder.count}</strong>
              </button>
              <IconButton
                className="folderDeleteButton"
                label={isSynced ? `Disable sync before deleting ${folder.name}` : `Delete ${folder.name}`}
                disabled={false}
                onClick={() => props.onDeleteFolder(folder.name)}
                icon={<TrashIcon />}
              />
            </div>
          );
        })}
      </div>
    </SidebarSection>
  );
}

function SidebarSection(props: { title: string; collapsed: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <div className="sidebarSection">
      <button
        className="sidebarSectionHeader"
        type="button"
        aria-expanded={!props.collapsed}
        onClick={props.onToggle}
      >
        <span>{props.title}</span>
        <strong>{props.collapsed ? "+" : "-"}</strong>
      </button>
      {!props.collapsed && <div className="sidebarSectionBody">{props.children}</div>}
    </div>
  );
}

function ShortcutDialog(props: {
  shortcut: Shortcut | null;
  folders: FolderItem[];
  initialFolder: string;
  onClose: () => void;
  onSave: (values: ShortcutFormValues) => Promise<void>;
}) {
  const [trigger, setTrigger] = useState(props.shortcut?.trigger ?? "");
  const [replace, setReplace] = useState(props.shortcut?.replace ?? "");
  const [form, setForm] = useState(props.shortcut?.form ?? "");
  const [formFieldsYaml, setFormFieldsYaml] = useState(props.shortcut?.form_fields_yaml ?? "");
  const [formFields, setFormFields] = useState<FormFieldDraft[]>(() => parseFormFieldsYaml(props.shortcut?.form_fields_yaml ?? ""));
  const [matchType, setMatchType] = useState<"replace" | "form" | "yaml">(props.shortcut?.form ? "form" : "replace");
  const [label, setLabel] = useState(props.shortcut?.label ?? "");
  const [word, setWord] = useState(Boolean(props.shortcut?.word));
  const [propagateCase, setPropagateCase] = useState(Boolean(props.shortcut?.propagate_case));
  const [caseInsensitive, setCaseInsensitive] = useState(Boolean(props.shortcut?.case_insensitive));
  const [uppercaseStyle, setUppercaseStyle] = useState(props.shortcut?.uppercase_style ?? "");
  const [forceMode, setForceMode] = useState(props.shortcut?.force_mode ?? "");
  const [folder, setFolder] = useState(props.shortcut?.folder ?? props.initialFolder);
  const [rawYaml, setRawYaml] = useState(props.shortcut?.raw_yaml ?? "");
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");
  const editingRaw = Boolean(props.shortcut && !props.shortcut.supported);
  const raw = editingRaw || matchType === "yaml";

  const changeMatchType = (nextType: "replace" | "form" | "yaml") => {
    if (nextType === "form" && !form && replace) setForm(replace);
    if (nextType === "replace" && !replace && form) setReplace(form);
    if (nextType === "yaml" && !rawYaml.trim()) setRawYaml('trigger: ":example"\nreplace: "Example replacement"\n');
    setMatchType(nextType);
  };

  const updateFormFields = (nextFields: FormFieldDraft[]) => {
    setFormFields(nextFields);
    setFormFieldsYaml(buildFormFieldsYaml(nextFields));
  };

  const addTemplateFields = () => {
    const existing = new Set(formFields.map((field) => field.name.trim()).filter(Boolean));
    const names = extractFormPlaceholders(form).filter((name) => !existing.has(name));
    if (names.length > 0) updateFormFields([...formFields, ...names.map((name) => createFormField(name))]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (raw && !rawYaml.trim()) {
      setLocalError("YAML is required.");
      return;
    }
    if (!raw && !trigger.trim()) {
      setLocalError("Trigger is required.");
      return;
    }
    if (!raw && matchType === "replace" && replace === "") {
      setLocalError("Replacement is required.");
      return;
    }
    if (!raw && matchType === "form" && !form.trim()) {
      setLocalError("Form template is required.");
      return;
    }
    if (!raw && matchType === "form") {
      const formValidation = validateFormTemplateFields(form, formFieldsYaml);
      if (formValidation.error) {
        setLocalError(formValidation.error);
        return;
      }
      if (formValidation.warning && !window.confirm(`${formValidation.warning} Save anyway?`)) {
        return;
      }
    }
    setSaving(true);
    setLocalError("");
    await props.onSave({
      matchType,
      trigger,
      replace,
      form,
      form_fields_yaml: formFieldsYaml,
      label,
      word,
      propagate_case: propagateCase,
      case_insensitive: caseInsensitive,
      uppercase_style: uppercaseStyle,
      force_mode: forceMode,
      folder,
      raw_yaml: rawYaml,
      raw
    });
    setSaving(false);
  };

  return (
    <div className="modalBackdrop">
      <form className="modal" onSubmit={submit}>
        <div className="toolbar">
          <h2>{props.shortcut ? "Edit Shortcut" : "Add Shortcut"}</h2>
          <div className="toolbarActions">
            <button className="primary" disabled={saving} type="submit">
              {saving ? "Saving..." : "Save"}
            </button>
            <button type="button" onClick={props.onClose}>
              Close
            </button>
          </div>
        </div>
        {props.shortcut && <div className="source">Source: {props.shortcut.file}</div>}
        {localError && <div className="formError">{localError}</div>}
        {editingRaw ? (
          <label>
            Match YAML
            <textarea
              className="codeInput"
              value={rawYaml}
              onChange={(event) => setRawYaml(event.target.value)}
              onKeyDown={(event) => handleCodeTextareaKeyDown(event, setRawYaml)}
              rows={14}
            />
          </label>
        ) : (
          <>
            <label>
              Folder
              <FolderInput value={folder} folders={props.folders} onChange={setFolder} />
            </label>
            <label>
              Match type
              <select value={matchType} onChange={(event) => changeMatchType(event.target.value as "replace" | "form" | "yaml")}>
                <option value="replace">Text replacement</option>
                <option value="form">Form</option>
                {!props.shortcut && <option value="yaml">Raw YAML</option>}
              </select>
            </label>
            {matchType === "yaml" ? (
              <label>
                Match YAML
                <textarea
                  className="codeInput"
                  value={rawYaml}
                  onChange={(event) => setRawYaml(event.target.value)}
                  onKeyDown={(event) => handleCodeTextareaKeyDown(event, setRawYaml)}
                  rows={14}
                  placeholder={'trigger: ":date"\nreplace: "{{today}}"\nvars:\n  - name: today\n    type: date'}
                />
              </label>
            ) : (
              <>
                <label>
                  Trigger
                  <input value={trigger} onChange={(event) => setTrigger(event.target.value)} placeholder=":nfse" />
                </label>
                {matchType === "replace" ? (
              <label>
                Replacement
                <textarea value={replace} onChange={(event) => setReplace(event.target.value)} rows={8} />
              </label>
                ) : (
              <>
                <label>
                  <LabelWithInfo text="Form template" info="Use double square brackets for fields Espanso should ask for, like [[name]], [[order_id]], or [[message]]. Reuse the same placeholder wherever the same answer should appear. Add matching field options below when you need textarea, choice, or list controls." />
                  <textarea value={form} onChange={(event) => setForm(event.target.value)} rows={8} placeholder={"Hi [[name]],\n\nYour order [[order_id]] is ready."} />
                </label>
                <FormFieldBuilder
                  fields={formFields}
                  onChange={updateFormFields}
                  onAddTemplateFields={addTemplateFields}
                />
                <label>
                  <LabelWithInfo text="Form fields YAML" info="This is the Espanso form_fields mapping generated by the visual builder. Edit it directly for advanced Espanso form options; using the builder again will regenerate this YAML." />
                  <textarea
                    className="codeInput compactCodeInput"
                    value={formFieldsYaml}
                    onChange={(event) => setFormFieldsYaml(event.target.value)}
                    onKeyDown={(event) => handleCodeTextareaKeyDown(event, setFormFieldsYaml)}
                    rows={7}
                    placeholder={"name:\n  type: text\norder_id:\n  type: text"}
                  />
                </label>
              </>
                )}
                <label>
                  Label
                  <input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Optional display name" />
                </label>
                <div className="optionGrid">
                  <label className="checkRow">
                    <input type="checkbox" checked={word} onChange={(event) => setWord(event.target.checked)} />
                    <span>Word trigger</span>
                    <InfoButton text="Only expands when the trigger is a complete word, so it will not fire inside another word. Use this for plain-word triggers that should wait for a word boundary." />
                  </label>
                  <label className="checkRow">
                    <input type="checkbox" checked={propagateCase} onChange={(event) => setPropagateCase(event.target.checked)} />
                    <span>Propagate case</span>
                    <InfoButton text="Matches the replacement casing to how you typed the trigger. Use it when the same shortcut should work in lowercase, Title Case, or uppercase contexts." />
                  </label>
                  <label className="checkRow">
                    <input type="checkbox" checked={caseInsensitive} onChange={(event) => setCaseInsensitive(event.target.checked)} />
                    <span>Case-insensitive trigger</span>
                    <InfoButton text="Expands when the trigger is typed with different letter casing, such as .nfsABN for a .nfsabn trigger." />
                  </label>
                </div>
                <label>
                  Uppercase style
                  <select value={uppercaseStyle} onChange={(event) => setUppercaseStyle(event.target.value)}>
                    <option value="">Default</option>
                    <option value="capitalize">Capitalize</option>
                    <option value="uppercase">Uppercase</option>
                  </select>
                </label>
                <label>
                  <LabelWithInfo text="Force mode" info="Default uses Espanso's global injection setting. Clipboard pastes the replacement through the clipboard, which is usually faster for long text but may briefly overwrite clipboard contents. Keys types the replacement as keystrokes, which can work better in apps that block clipboard paste but is slower." />
                  <select value={forceMode} onChange={(event) => setForceMode(event.target.value)}>
                    <option value="">Default</option>
                    <option value="clipboard">Clipboard</option>
                    <option value="keys">Keys</option>
                  </select>
                </label>
              </>
            )}
          </>
        )}
        <button className="primary" disabled={saving} type="submit">
          {saving ? "Saving..." : "Save"}
        </button>
      </form>
    </div>
  );
}

function FormFieldBuilder(props: {
  fields: FormFieldDraft[];
  onChange: (fields: FormFieldDraft[]) => void;
  onAddTemplateFields: () => void;
}) {
  const updateField = (id: string, patch: Partial<FormFieldDraft>) => {
    props.onChange(props.fields.map((field) => (field.id === id ? { ...field, ...patch } : field)));
  };

  const removeField = (id: string) => {
    props.onChange(props.fields.filter((field) => field.id !== id));
  };

  return (
    <div className="formBuilder">
      <div className="formBuilderHeader">
        <LabelWithInfo text="Form fields" info="Define the controls Espanso shows when this form expands. Add from template creates fields for placeholders in the form template; Add field creates one manually." />
        <div className="toolbarActions">
          <button type="button" onClick={props.onAddTemplateFields}>Add from template</button>
          <button type="button" onClick={() => props.onChange([...props.fields, createFormField()])}>Add field</button>
        </div>
      </div>
      {props.fields.length === 0 && <div className="empty compactEmpty">No visual fields configured.</div>}
      {props.fields.map((field) => (
        <div className="fieldRow" key={field.id}>
          <input aria-label="Field name" value={field.name} onChange={(event) => updateField(field.id, { name: event.target.value })} placeholder="field_name" />
          <div className="fieldTypeControl">
            <select aria-label="Field type" value={field.type} onChange={(event) => updateField(field.id, { type: event.target.value as FormFieldType })}>
              <option value="text">Text</option>
              <option value="multiline">Multiline</option>
              <option value="choice">Choice</option>
              <option value="list">List</option>
            </select>
            <InfoButton text="Text creates a single-line input. Multiline creates a larger text box. Choice and List use the options you enter below, one option per line." />
          </div>
          <button type="button" onClick={() => removeField(field.id)}>Remove</button>
          {(field.type === "choice" || field.type === "list") && (
            <div className="fieldValuesGroup">
              <LabelWithInfo text="Options" info="For Choice or List fields, enter each selectable value on its own line. These become the values Espanso shows in the form." />
              <textarea
                className="fieldValues"
                value={field.values}
                onChange={(event) => updateField(field.id, { values: event.target.value })}
                placeholder="One option per line"
                rows={3}
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function LabelWithInfo({ text, info }: { text: string; info: string }) {
  return (
    <span className="labelWithInfo">
      {text}
      <InfoButton text={info} />
    </span>
  );
}

function InfoButton({ text, linkUrl, linkLabel }: { text: string; linkUrl?: string; linkLabel?: string }) {
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const hideTimer = useRef<number | null>(null);

  const clearHideTimer = () => {
    if (hideTimer.current !== null) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  };

  const scheduleHide = () => {
    clearHideTimer();
    hideTimer.current = window.setTimeout(() => {
      setPosition(null);
      hideTimer.current = null;
    }, 250);
  };

  useEffect(() => clearHideTimer, []);

  const show = (target: HTMLElement) => {
    clearHideTimer();
    const rect = target.getBoundingClientRect();
    const tooltipWidth = Math.min(320, window.innerWidth - 32);
    const left = Math.min(Math.max(16, rect.left + rect.width / 2 - tooltipWidth / 2), window.innerWidth - tooltipWidth - 16);
    const top = Math.min(rect.bottom + 8, window.innerHeight - 180);
    setPosition({ left, top });
  };

  return (
    <span className="infoButtonWrap" onMouseLeave={scheduleHide}>
      <button
        className="infoButton"
        type="button"
        aria-label={text}
        onBlur={scheduleHide}
        onFocus={(event) => show(event.currentTarget)}
        onMouseEnter={(event) => show(event.currentTarget)}
      >
        i
      </button>
      {position && (
        <span
          className="tooltip visibleTooltip"
          role="tooltip"
          style={{ left: position.left, top: position.top }}
          onBlur={scheduleHide}
          onFocus={clearHideTimer}
          onMouseEnter={clearHideTimer}
          onMouseLeave={scheduleHide}
        >
          {text}
          {linkUrl && (
            <a href={linkUrl} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>
              {linkLabel ?? linkUrl}
            </a>
          )}
        </span>
      )}
    </span>
  );
}

function MoveDialog(props: { shortcut: Shortcut; folders: FolderItem[]; onClose: () => void; onMove: (folder: string) => Promise<void> }) {
  const [folder, setFolder] = useState(props.shortcut.folder);
  const [moving, setMoving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setMoving(true);
    await props.onMove(folder);
    setMoving(false);
  };

  return (
    <div className="modalBackdrop">
      <form className="modal smallModal" onSubmit={submit}>
        <div className="toolbar">
          <h2>Move Shortcut</h2>
          <button type="button" onClick={props.onClose}>Close</button>
        </div>
        <div className="source">Current folder: {props.shortcut.folder}</div>
        <label>
          Destination folder
          <FolderInput value={folder} folders={props.folders} onChange={setFolder} />
        </label>
        <button className="primary" disabled={moving} type="submit">
          {moving ? "Moving..." : "Move"}
        </button>
      </form>
    </div>
  );
}

function FolderDialog(props: { folders: FolderItem[]; onClose: () => void; onCreate: (folder: string) => Promise<void> }) {
  const [folder, setFolder] = useState("");
  const [creating, setCreating] = useState(false);
  const [localError, setLocalError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!folder.trim() || folder.trim() === "Root") {
      setLocalError("Folder name is required.");
      return;
    }
    setCreating(true);
    setLocalError("");
    await props.onCreate(folder);
    setCreating(false);
  };

  return (
    <div className="modalBackdrop">
      <form className="modal smallModal" onSubmit={submit}>
        <div className="toolbar">
          <h2>New Folder</h2>
          <button type="button" onClick={props.onClose}>Close</button>
        </div>
        {localError && <div className="formError">{localError}</div>}
        <label>
          Folder name
          <FolderInput value={folder} folders={props.folders} onChange={setFolder} />
        </label>
        <button className="primary" disabled={creating} type="submit">
          {creating ? "Creating..." : "Create"}
        </button>
      </form>
    </div>
  );
}

function MacOSImportDialog(props: {
  folders: FolderItem[];
  initialFolder: string;
  onClose: () => void;
  onImport: (folder: string, replacements: MacOSTextReplacementItem[]) => Promise<MacOSTextReplacementImportResult>;
}) {
  const [folder, setFolder] = useState(props.initialFolder);
  const [preview, setPreview] = useState<MacOSTextReplacementPreview | null>(null);
  const [selectedIndexes, setSelectedIndexes] = useState<Set<number>>(new Set());
  const [loadingPreview, setLoadingPreview] = useState(true);
  const [importing, setImporting] = useState(false);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    let active = true;
    api<MacOSTextReplacementPreview>("/api/import/macos-text-replacements")
      .then((result) => {
        if (active) {
          setPreview(result);
          setSelectedIndexes(new Set(result.items.map((item, index) => (isImportableMacOSReplacement(item) ? index : -1)).filter((index) => index >= 0)));
        }
      })
      .catch((err) => {
        if (active) setLocalError(normalizeError(err).message);
      })
      .finally(() => {
        if (active) setLoadingPreview(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const importableIndexes = preview?.items.map((item, index) => (isImportableMacOSReplacement(item) ? index : -1)).filter((index) => index >= 0) ?? [];
  const importableCount = importableIndexes.length;
  const selectedCount = selectedIndexes.size;
  const allImportableSelected = importableCount > 0 && selectedCount === importableCount;

  const toggleSelected = (index: number, checked: boolean) => {
    setSelectedIndexes((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(index);
      } else {
        next.delete(index);
      }
      return next;
    });
  };

  const selectAll = () => setSelectedIndexes(new Set(importableIndexes));
  const clearSelection = () => setSelectedIndexes(new Set());

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!preview || selectedCount === 0) {
      setLocalError("Select at least one replacement to import.");
      return;
    }
    setImporting(true);
    setLocalError("");
    try {
      const replacements = [...selectedIndexes].sort((a, b) => a - b).map((index) => preview.items[index]);
      await props.onImport(folder, replacements);
    } catch (err) {
      setLocalError(normalizeError(err).message);
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="modalBackdrop">
      <form className="modal importModal" onSubmit={submit}>
        <div className="toolbar">
          <h2>Import from macOS</h2>
          <div className="toolbarActions">
            <button className="primary" disabled={loadingPreview || importing || selectedCount === 0} type="submit">
              {importing ? "Importing..." : `Import ${selectedCount}`}
            </button>
            <button type="button" onClick={props.onClose}>Close</button>
          </div>
        </div>
        {localError && <div className="formError">{localError}</div>}
        <label>
          Destination folder
          <FolderInput value={folder} folders={props.folders} onChange={setFolder} />
        </label>
        {loadingPreview && <div className="empty compactEmpty">Loading macOS replacements...</div>}
        {!loadingPreview && preview && (
          <>
            <div className="importSummary">
              <strong>{selectedCount} of {importableCount}</strong>
              <span>{macOSImportSourceLabel(preview)}</span>
            </div>
            {importableCount > 0 && (
              <div className="importSelectionActions">
                <button type="button" disabled={allImportableSelected} onClick={selectAll}>Select all</button>
                <button type="button" disabled={selectedCount === 0} onClick={clearSelection}>Ignore all</button>
              </div>
            )}
            {!preview.available && <div className="empty compactEmpty">macOS text replacements were not found on this machine.</div>}
            {preview.unsupported_count > 0 && <div className="source">{preview.unsupported_count} entries were ignored because they were not in the expected macOS format.</div>}
            <div className="importPreview">
              <div className="importPreviewRow header">
                <span>
                  <input
                    aria-label="Select all importable replacements"
                    checked={allImportableSelected}
                    disabled={importableCount === 0}
                    type="checkbox"
                    onChange={(event) => (event.target.checked ? selectAll() : clearSelection())}
                  />
                </span>
                <span>Trigger</span>
                <span>Replacement</span>
                <span>Status</span>
              </div>
              {preview.items.map((item, index) => (
                <div className="importPreviewRow" key={`${item.trigger}-${index}`}>
                  <span>
                    <input
                      aria-label={`Import ${item.trigger || "replacement"}`}
                      checked={selectedIndexes.has(index)}
                      disabled={!isImportableMacOSReplacement(item)}
                      type="checkbox"
                      onChange={(event) => toggleSelected(index, event.target.checked)}
                    />
                  </span>
                  <strong>{item.trigger || "Empty trigger"}</strong>
                  <span>{item.replacement || "Empty replacement"}</span>
                  <StatusPill ok={item.enabled} label={item.enabled ? "Enabled" : "Disabled"} />
                </div>
              ))}
              {preview.items.length === 0 && <div className="empty compactEmpty">No text replacements found.</div>}
            </div>
          </>
        )}
      </form>
    </div>
  );
}

function FolderInput(props: { value: string; folders: FolderItem[]; onChange: (value: string) => void }) {
  const folderNames = ["Root", ...props.folders.filter((folder) => folder.name !== "Root").map((folder) => folder.name)];
  const selectValue = folderNames.includes(props.value) ? props.value : "__custom__";

  return (
    <div className="folderInput">
      <select
        value={selectValue}
        onChange={(event) => props.onChange(event.target.value === "__custom__" ? "" : event.target.value)}
      >
        {folderNames.map((folder) => (
          <option key={folder} value={folder}>{folder}</option>
        ))}
        <option value="__custom__">Custom folder...</option>
      </select>
      {selectValue === "__custom__" && (
        <input value={props.value} onChange={(event) => props.onChange(event.target.value)} placeholder="work/email" />
      )}
    </div>
  );
}

function HealthView({ status, onValidate }: { status: Status | null; onValidate: () => void }) {
  if (!status) return <section><h1>Health</h1></section>;
  return (
    <section>
      <div className="toolbar">
        <h1>Health</h1>
        <button className="primary" onClick={onValidate}>Run validation</button>
      </div>
      <div className="statusGrid">
        <HealthRow label="Espanso installed" value={status.installed ? "Yes" : "No"} ok={status.installed} />
        <HealthRow label="Version" value={status.version ?? "Unknown"} ok={Boolean(status.version)} />
        <HealthRow label="Running" value={status.running ? "Yes" : "No"} ok={status.running} />
        <HealthRow label="Config directory" value={status.config_path ?? "Not detected"} ok={Boolean(status.config_path)} />
        <HealthRow label="Match directory" value={status.match_path ?? "Not detected"} ok={Boolean(status.match_path)} />
        <HealthRow label="YAML valid" value={status.yaml_valid ? "Valid" : "Invalid"} ok={status.yaml_valid} />
        <HealthRow label="Duplicate triggers" value={String(status.duplicate_triggers.length)} ok={status.duplicate_triggers.length === 0} />
        <HealthRow label="Last reload" value={status.last_reload ? "Successful" : "No reload yet"} ok={Boolean(status.last_reload)} />
      </div>
      {status.duplicate_triggers.length > 0 && (
        <div className="panel">
          <h2>Duplicate Triggers</h2>
          {status.duplicate_triggers.map((duplicate) => (
            <p key={duplicate.trigger}>
              <strong>{duplicate.trigger}</strong> in {duplicate.files.join(", ")}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}

function HealthRow({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div className="healthRow">
      <span>{label}</span>
      <strong>{value}</strong>
      <StatusPill ok={ok} label={ok ? "OK" : "Check"} />
    </div>
  );
}

function PackagesView(props: {
  packages: PackageItem[];
  onInstall: (values: PackageInstallValues) => Promise<void>;
  onUpdate: (packageName: string) => Promise<void>;
  onRemove: (packageName: string) => Promise<void>;
}) {
  return (
    <section>
      <div className="toolbar">
        <h1>Packages</h1>
      </div>
      <PackageInstallPanel onInstall={props.onInstall} />
      <div className="table">
        <div className="row packageRow header">
          <span>Package</span>
          <span>Details</span>
          <span>Status</span>
          <span></span>
        </div>
        {props.packages.map((item) => (
          <div className="row packageRow" key={item.name}>
            <div className="packageName">
              <strong>{item.name}</strong>
              <span>{item.version ? `Version ${item.version}` : "Installed package"}</span>
            </div>
            <span className="preview">{item.description ?? `${item.shortcut_count} shortcuts across ${item.file_count} files`}</span>
            <StatusPill ok={item.yaml_valid} label={item.yaml_valid ? "Valid" : "Check"} />
            <span className="actions">
              <button onClick={() => props.onUpdate(item.name)}>Update</button>
              <button onClick={() => props.onRemove(item.name)}>Remove</button>
            </span>
          </div>
        ))}
        {props.packages.length === 0 && <div className="empty">No packages installed.</div>}
      </div>
    </section>
  );
}

function PackageInstallPanel({ onInstall }: { onInstall: (values: PackageInstallValues) => Promise<void> }) {
  const [values, setValues] = useState<PackageInstallValues>({
    name: "",
    git: "",
    version: "",
    branch: "",
    external: false,
    force: false,
    refresh_index: false,
    use_native_git: false
  });
  const [installing, setInstalling] = useState(false);
  const [localError, setLocalError] = useState("");

  const update = (patch: Partial<PackageInstallValues>) => setValues((current) => ({ ...current, ...patch }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!values.name.trim() && !values.git.trim()) {
      setLocalError("Enter a package name or Git repository URL.");
      return;
    }
    setInstalling(true);
    setLocalError("");
    await onInstall({
      ...values,
      name: values.name.trim(),
      git: values.git.trim(),
      version: values.version.trim(),
      branch: values.branch.trim()
    });
    setInstalling(false);
  };

  return (
    <form className="panel packageInstall" onSubmit={submit}>
      <div className="formBuilderHeader">
        <LabelWithInfo text="Install package" info="Install an Espanso Hub package by name, or install from a Git repository by adding a Git URL. Espanso handles the package download and writes it into match/packages." />
        <button className="primary" disabled={installing} type="submit">
          {installing ? "Installing..." : "Install"}
        </button>
      </div>
      {localError && <div className="formError">{localError}</div>}
      <div className="packageInstallGrid">
        <label>
          <LabelWithInfo text="Package name" info="Use the Espanso Hub package name, such as a package listed in the Hub. For Git installs, use the package folder name expected by that repository." />
          <input value={values.name} onChange={(event) => update({ name: event.target.value })} placeholder="basic-emojis" />
        </label>
        <label>
          <LabelWithInfo text="Git URL" info="Optional. Install from a Git repository instead of the verified Espanso Hub index. Enable External repository for non-verified sources." />
          <input value={values.git} onChange={(event) => update({ git: event.target.value })} placeholder="https://github.com/user/espanso-package.git" />
        </label>
        <label>
          <LabelWithInfo text="Version" info="Optional. Pin the package install to a specific package version instead of the latest version." />
          <input value={values.version} onChange={(event) => update({ version: event.target.value })} placeholder="Optional" />
        </label>
        <label>
          <LabelWithInfo text="Git branch" info="Optional. Use this when installing from a Git repository and the package lives on a branch other than the default branch." />
          <input value={values.branch} onChange={(event) => update({ branch: event.target.value })} placeholder="main" />
        </label>
      </div>
      <div className="optionGrid">
        <label className="checkRow">
          <input type="checkbox" checked={values.external} onChange={(event) => update({ external: event.target.checked })} />
          <span>External repository</span>
          <InfoButton text="Allows installing packages from non-verified repositories. Use this for Git sources you trust." />
        </label>
        <label className="checkRow">
          <input type="checkbox" checked={values.force} onChange={(event) => update({ force: event.target.checked })} />
          <span>Force reinstall</span>
          <InfoButton text="Overwrites the package if it is already installed. Useful when retrying an install or replacing local package files." />
        </label>
        <label className="checkRow">
          <input type="checkbox" checked={values.refresh_index} onChange={(event) => update({ refresh_index: event.target.checked })} />
          <span>Refresh index</span>
          <InfoButton text="Requests a fresh Espanso Hub package index before installing, instead of using Espanso's cached index." />
        </label>
        <label className="checkRow">
          <input type="checkbox" checked={values.use_native_git} onChange={(event) => update({ use_native_git: event.target.checked })} />
          <span>Use native git</span>
          <InfoButton text="Tells Espanso to use the installed git command for Git package installs. Use this if the default download method fails." />
        </label>
      </div>
    </form>
  );
}

function SettingsView(props: {
  settings: AppSettings | null;
  folders: FolderItem[];
  onSave: (settings: AppSettings) => Promise<AppSettings>;
  onValidateGitSync: (source: GitSyncSource) => Promise<GitSyncValidation>;
  onSyncGit: () => Promise<GitSyncResult>;
  onDisableGitSyncSource: (source: GitSyncSource, removeShortcuts: boolean) => Promise<GitSyncResult>;
}) {
  const [gitSync, setGitSync] = useState<GitSyncSettings>(() => props.settings?.git_sync ?? defaultGitSyncSettings());
  const [theme, setTheme] = useState<ThemeMode>(() => props.settings?.theme ?? "dark");
  const [validations, setValidations] = useState<Record<string, GitSyncValidation>>({});
  const [saving, setSaving] = useState(false);
  const [validatingId, setValidatingId] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (props.settings) {
      setGitSync(props.settings.git_sync);
      setTheme(props.settings.theme);
    }
  }, [props.settings]);

  const updateSettings = (patch: Partial<GitSyncSettings>) => {
    setGitSync((current) => ({ ...current, ...patch }));
  };

  const updateSource = (sourceId: string, patch: Partial<GitSyncSource>) => {
    setGitSync((current) => ({
      ...current,
      sources: current.sources.map((source) => (source.id === sourceId ? { ...source, ...patch } : source))
    }));
    setValidations((current) => {
      const next = { ...current };
      delete next[sourceId];
      return next;
    });
  };

  const addSource = () => {
    setGitSync((current) => ({
      ...current,
      sources: [...current.sources, defaultGitSyncSource()]
    }));
  };

  const removeSource = (sourceId: string) => {
    setGitSync((current) => ({
      ...current,
      sources: current.sources.filter((source) => source.id !== sourceId)
    }));
  };

  const normalized = normalizeGitSyncSettings(gitSync);

  const validate = async (source: GitSyncSource) => {
    const normalizedSource = normalizeGitSyncSource(source);
    if (!normalizedSource.repo_url) {
      setLocalError("Enter a GitHub repository URL.");
      return null;
    }
    setValidatingId(source.id);
    setLocalError("");
    try {
      const result = await props.onValidateGitSync(normalizedSource);
      setValidations((current) => ({ ...current, [source.id]: result }));
      return result;
    } catch (err) {
      setLocalError(normalizeError(err).message);
      return null;
    } finally {
      setValidatingId(null);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const hasInvalidEnabledSource = normalized.sources.some((source) => source.enabled && !source.repo_url);
    if (normalized.enabled && hasInvalidEnabledSource) {
      setLocalError("Enabled sources need a GitHub repository URL.");
      return;
    }
    setSaving(true);
    setLocalError("");
    try {
      const saved = await props.onSave({ theme, git_sync: normalized, backup: props.settings?.backup ?? defaultBackupSettings() });
      setGitSync(saved.git_sync);
      setTheme(saved.theme);
    } catch (err) {
      setLocalError(normalizeError(err).message);
    } finally {
      setSaving(false);
    }
  };

  const syncNow = async () => {
    setSyncing(true);
    setLocalError("");
    try {
      const result = await props.onSyncGit();
      if (result.settings) setGitSync(result.settings.git_sync);
      if (result.validations.length > 0) {
        setValidations(Object.fromEntries(result.validations.map((validation) => [validation.source_id ?? "", validation])));
      }
    } catch (err) {
      setLocalError(normalizeError(err).message);
    } finally {
      setSyncing(false);
    }
  };

  const toggleSourceEnabled = async (source: GitSyncSource, checked: boolean) => {
    if (checked) {
      updateSource(source.id, { enabled: true });
      return;
    }
    const savedSource = props.settings?.git_sync.sources.find((item) => item.id === source.id);
    if (!savedSource?.enabled) {
      updateSource(source.id, { enabled: false });
      return;
    }
    const disable = window.confirm("Disable GitHub sync for this repository?");
    if (!disable) return;
    const removeShortcuts = window.confirm("Remove the shortcuts that were installed from this GitHub sync source? Choose Cancel to keep them locally.");
    setSyncing(true);
    setLocalError("");
    try {
      const result = await props.onDisableGitSyncSource(source, removeShortcuts);
      if (result.settings) setGitSync(result.settings.git_sync);
    } catch (err) {
      setLocalError(normalizeError(err).message);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <section>
      <div className="toolbar">
        <h1>Settings</h1>
      </div>
      <form className="panel settingsPanel" onSubmit={submit}>
        <div className="formBuilderHeader">
          <LabelWithInfo text="GitHub shortcut sync" info="When enabled, EspansoEdit checks each configured GitHub repository at launch and installs every selected Espanso match file into that source's destination folder." />
          <div className="toolbarActions">
            <button type="button" onClick={addSource}>Add repo</button>
            <button type="button" disabled={syncing || !props.settings?.git_sync.enabled} onClick={syncNow}>
              {syncing ? "Syncing..." : "Sync now"}
            </button>
            <button className="primary" disabled={saving} type="submit">
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
        {localError && <div className="formError">{localError}</div>}
        <div className="optionGrid">
          <label className="checkRow">
            <input type="checkbox" checked={theme === "dark"} onChange={(event) => setTheme(event.target.checked ? "dark" : "light")} />
            <span>Dark mode</span>
            <InfoButton text="Switches EspansoEdit between the dark VirtualBuddy-style theme and a lighter macOS-style theme." />
          </label>
          <label className="checkRow">
            <input type="checkbox" checked={gitSync.enabled} onChange={(event) => updateSettings({ enabled: event.target.checked })} />
            <span>Sync on app launch</span>
            <InfoButton text="Runs all enabled GitHub sync sources when the desktop app starts. Manual Sync now remains available from this Settings page." />
          </label>
        </div>
        <div className="syncSourceList">
          {gitSync.sources.map((source, index) => {
            const validation = validations[source.id];
            const sourceSyncMode = syncModeForSource(source, validation);
            const sourceLabel = syncSourceLabel(source, index);
            const branchOptions = gitBranchOptions(source, validation);
            const filePathsText = source.file_paths.join("\n");
            return (
              <div className="syncSourceCard" key={source.id}>
                <div className="formBuilderHeader">
                  <h2>
                    {sourceLabel}
                    <StatusPill ok={sourceSyncMode === "two_way"} label={sourceSyncMode === "two_way" ? "2-way sync" : "1-way sync"} />
                  </h2>
                  <div className="toolbarActions">
                    <button type="button" disabled={validatingId === source.id || !source.repo_url} onClick={() => validate(source)}>
                      {validatingId === source.id ? "Validating..." : "Validate"}
                    </button>
                    <button type="button" onClick={() => removeSource(source.id)}>Remove</button>
                  </div>
                </div>
                <div className="settingsColumns">
                  <div className="settingsColumn">
                    <label>
                      <span className="labelWithInfo">
                        Sync name
                        <InfoButton text="A friendly local label for this sync source. It only changes how the sync is shown in EspansoEdit." />
                      </span>
                      <input
                        value={source.name ?? ""}
                        onChange={(event) => updateSource(source.id, { name: event.target.value })}
                        placeholder={`Repository ${index + 1}`}
                      />
                    </label>
                    <label>
                      <span className="labelWithInfo">
                        Repository URL
                        <InfoButton text="The GitHub repository that contains one or more Espanso YAML match files. Use the repository URL, or a GitHub file URL to preselect one file." />
                      </span>
                      <input
                        value={source.repo_url ?? ""}
                        onChange={(event) => updateSource(source.id, { repo_url: event.target.value })}
                        placeholder="https://github.com/user/espanso-shortcuts"
                      />
                    </label>
                    <label>
                      <span className="labelWithInfo">
                        Access token
                        <InfoButton
                          text="Private repositories need a fine-grained GitHub personal access token with Contents read access. Set Contents to Read and write to let EspansoEdit push local synced-folder changes back to GitHub."
                          linkUrl="https://github.com/settings/personal-access-tokens/new"
                          linkLabel="Create token"
                        />
                      </span>
                      <input
                        type="password"
                        value={source.access_token ?? ""}
                        onChange={(event) => updateSource(source.id, { access_token: event.target.value })}
                        placeholder="Required for private repositories"
                      />
                    </label>
                    <label className="checkRow">
                      <input type="checkbox" checked={source.enabled} onChange={(event) => toggleSourceEnabled(source, event.target.checked)} />
                      <span>Enabled</span>
                      <InfoButton text="Includes this repository when GitHub shortcut sync runs." />
                    </label>
                  </div>
                  <div className="settingsColumn">
                    <label>
                      <span className="labelWithInfo">
                        Branch
                        <InfoButton text="The Git branch to sync from. Click Validate after entering the repository URL and token to load available branches from GitHub." />
                      </span>
                      {branchOptions.length ? (
                        <select
                          value={source.branch || validation?.branch || branchOptions[0]}
                          onChange={(event) => updateSource(source.id, { branch: event.target.value })}
                        >
                          {branchOptions.map((branch) => (
                            <option key={branch} value={branch}>{branch}</option>
                          ))}
                        </select>
                      ) : (
                        <select
                          value={source.branch ?? ""}
                          onChange={(event) => updateSource(source.id, { branch: event.target.value })}
                        >
                          <option value="">Default branch</option>
                          {source.branch && <option value={source.branch}>{source.branch}</option>}
                        </select>
                      )}
                    </label>
                    <label>
                      <span className="labelWithInfo">
                        Destination folder
                        <InfoButton text="The local Espanso folder where shortcuts from this sync source are installed. Synced folders are protected from deletion while sync is enabled." />
                      </span>
                      <FolderInput value={source.folder || "GitHub"} folders={props.folders} onChange={(folder) => updateSource(source.id, { folder })} />
                    </label>
                    <label>
                      <span className="labelWithInfo">
                        Match file paths
                        <InfoButton text="Optional list of Espanso YAML files to sync, one path per line. Leave blank to auto-detect YAML files that contain a matches list." />
                      </span>
                      <textarea
                        className="codeInput compactCodeInput"
                        value={filePathsText}
                        onChange={(event) => updateSource(source.id, { file_paths: linesToFilePaths(event.target.value) })}
                        placeholder={"Auto-detect all Espanso YAML files\nor enter one path per line"}
                        rows={5}
                      />
                    </label>
                  </div>
                </div>
                {validation && (
                  <div className="syncStatus">
                    <StatusPill ok={validation.shortcut_file_found} label={validation.shortcut_file_found ? "Valid" : "Check"} />
                    {validation.shortcut_file_found && <StatusPill ok={validation.write_access} label={validation.write_access ? "Read/write" : "Read-only"} />}
                    <span>{validation.message}</span>
                    {validation.files.map((file) => (
                      <strong key={file.file_path}>{file.file_path}</strong>
                    ))}
                  </div>
                )}
                <div className="settingsMeta">
                  <span>Last sync: {source.last_synced_at ?? "Never"}</span>
                  <span>{source.last_sync_message ?? (source.write_access ? "Two-way sync ready after first sync." : "No sync result yet.")}</span>
                </div>
              </div>
            );
          })}
        </div>
        {gitSync.sources.length === 0 && (
          <div className="empty compactEmpty">No GitHub repositories configured.</div>
        )}
      </form>
    </section>
  );
}

function BackupsView({
  backups,
  settings,
  onRestore,
  onSaveSettings,
  onMoveLocation,
  onClear,
  onSync,
  onValidateGitHub,
}: {
  backups: Backup[];
  settings: BackupSettings;
  onRestore: (backup: Backup) => void;
  onSaveSettings: (settings: BackupSettings) => Promise<BackupSettings>;
  onMoveLocation: () => Promise<BackupSettings | undefined>;
  onClear: () => Promise<void>;
  onSync: () => Promise<BackupSyncResult>;
  onValidateGitHub: (settings: BackupSettings) => Promise<BackupGitHubValidation>;
}) {
  const [draft, setDraft] = useState<BackupSettings>(() => normalizeBackupSettings(settings));
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [moving, setMoving] = useState(false);
  const [settingsExpanded, setSettingsExpanded] = useState(true);
  const [validation, setValidation] = useState<BackupGitHubValidation | null>(null);

  useEffect(() => {
    setDraft(normalizeBackupSettings(settings));
  }, [settings]);

  const updateDraft = (patch: Partial<BackupSettings>) => {
    setDraft((current) => ({ ...current, ...patch }));
  };

  const branchOptions = backupBranchOptions(draft, validation ?? undefined);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      const updated = await onSaveSettings(draft);
      setDraft(normalizeBackupSettings(updated));
    } finally {
      setSaving(false);
    }
  };

  const moveLocation = async () => {
    setMoving(true);
    try {
      const updated = await onMoveLocation();
      if (updated) setDraft(normalizeBackupSettings(updated));
    } finally {
      setMoving(false);
    }
  };

  const syncNow = async () => {
    setSyncing(true);
    try {
      const result = await onSync();
      if (result.settings) setDraft(normalizeBackupSettings(result.settings));
    } finally {
      setSyncing(false);
    }
  };

  const validateGitHub = async () => {
    setSyncing(true);
    try {
      const result = await onValidateGitHub(draft);
      setValidation(result);
      updateDraft({ github_branch: result.branch ?? draft.github_branch });
    } finally {
      setSyncing(false);
    }
  };

  return (
    <section>
      <div className="toolbar">
        <h1>Backups</h1>
        <div className="actions">
          <button type="button" onClick={moveLocation} disabled={moving}>
            {moving ? "Moving..." : "Move Location"}
          </button>
          <button type="button" onClick={onClear} disabled={backups.length === 0}>
            Clear Backups
          </button>
        </div>
      </div>
      <form className={`panel backupSettingsPanel ${settingsExpanded ? "expanded" : "collapsed"}`} onSubmit={save}>
        <button
          className="collapsibleHeader"
          type="button"
          aria-expanded={settingsExpanded}
          onClick={() => setSettingsExpanded((value) => !value)}
        >
          <span>Backup settings</span>
          <span className="collapsibleMeta">{draft.location ?? "Default Espanso config folder"}</span>
          <span className="collapsibleChevron">{settingsExpanded ? "⌃" : "⌄"}</span>
        </button>
        {settingsExpanded && (
          <div className="backupSettingsContent">
            <div className="backupGeneralGroup">
              <div className="settingsColumn">
                <label>
                  <LabelWithInfo
                    text="Backup frequency"
                    info="Controls automatic safety backups before shortcut files are changed. Manual-only keeps existing backups but stops creating new automatic backups."
                  />
                  <select value={draft.frequency} onChange={(event) => updateDraft({ frequency: event.target.value as BackupFrequency })}>
                    <option value="always">Every change</option>
                    <option value="daily">Daily per file</option>
                    <option value="manual">Manual only</option>
                  </select>
                </label>
              </div>
              <div className="settingsMeta backupLocationMeta">
                <span>Current location</span>
                <strong>{draft.location ?? "Default Espanso config folder"}</strong>
              </div>
            </div>
            <div className="backupGitHubGroup">
              <div className="backupGroupHeader">
                <label className="checkboxLabel">
                  <input
                    type="checkbox"
                    checked={draft.github_enabled}
                    onChange={(event) => updateDraft({ github_enabled: event.target.checked })}
                  />
                  Sync backups to GitHub
                  <InfoButton text="Uploads local backup files to a GitHub repository path. This is one-way backup storage and requires a token with Contents read and write access." />
                </label>
                <div className="settingsMeta">
                  <span>Last sync: {draft.last_synced_at ?? "Never"}</span>
                  <span>{draft.last_sync_message ?? "No backup sync result yet."}</span>
                </div>
              </div>
              <div className="backupGithubGrid">
                <label>
                  <LabelWithInfo text="Repository URL" info="GitHub repository that will store backup files. Use the repository URL, not a shortcut file URL." />
                  <input
                    value={draft.github_repo_url ?? ""}
                    onChange={(event) => {
                      setValidation(null);
                      updateDraft({ github_repo_url: event.target.value });
                    }}
                    placeholder="https://github.com/owner/repo"
                  />
                </label>
                <label>
                  <LabelWithInfo text="Branch" info="Branch where backup files should be stored. Leave blank to use the repository default branch." />
                  {branchOptions.length ? (
                    <select value={draft.github_branch || validation?.branch || branchOptions[0]} onChange={(event) => updateDraft({ github_branch: event.target.value })}>
                      {branchOptions.map((branch) => (
                        <option key={branch} value={branch}>{branch}</option>
                      ))}
                    </select>
                  ) : (
                    <select value={draft.github_branch ?? ""} onChange={(event) => updateDraft({ github_branch: event.target.value })}>
                      <option value="">Default branch</option>
                      {draft.github_branch && <option value={draft.github_branch}>{draft.github_branch}</option>}
                    </select>
                  )}
                </label>
                <label className="backupSecondRow">
                  <LabelWithInfo text="Repository path" info="Folder path inside the GitHub repository where backup folders and metadata files are uploaded." />
                  <input
                    value={draft.github_path}
                    onChange={(event) => updateDraft({ github_path: event.target.value })}
                    placeholder="espansoedit-backups"
                  />
                </label>
                <label className="backupSecondRow">
                  <LabelWithInfo text="Access token" info="Use a fine-grained GitHub token with Contents read and write access for the selected repository." />
                  <input
                    type="password"
                    value={draft.github_access_token ?? ""}
                    onChange={(event) => updateDraft({ github_access_token: event.target.value })}
                    placeholder="github_pat_..."
                  />
                </label>
              </div>
              {validation && (
                <div className="syncStatus">
                  <StatusPill ok={validation.exists} label={validation.exists ? "Found" : "Check"} />
                  <StatusPill ok={validation.write_access} label={validation.write_access ? "Read/write" : "Read-only"} />
                  <span>{validation.message}</span>
                </div>
              )}
              <div className="buttonRow">
                <button type="button" disabled={syncing || !draft.github_repo_url} onClick={validateGitHub}>
                  Validate
                </button>
                <button className="primary" type="submit" disabled={saving}>
                  {saving ? "Saving..." : "Save Backup Settings"}
                </button>
                <button type="button" disabled={syncing || !draft.github_enabled} onClick={syncNow}>
                  {syncing ? "Syncing..." : "Sync Backups Now"}
                </button>
              </div>
            </div>
          </div>
        )}
      </form>
      <div className="table">
        <div className="row header">
          <span>Timestamp</span>
          <span>File</span>
          <span>Operation</span>
          <span></span>
        </div>
        {backups.map((backup) => (
          <div className="row backupRow" key={backup.id}>
            <span>{backup.timestamp}</span>
            <span>{fileName(backup.original_path)}</span>
            <span>{backup.operation}</span>
            <button type="button" onClick={() => onRestore(backup)}>Restore</button>
          </div>
        ))}
        {backups.length === 0 && <div className="empty">No backups found.</div>}
      </div>
    </section>
  );
}

function ConfigView({ config, onSave }: { config: ConfigPayload | null; onSave: (values: ConfigValue[]) => Promise<ConfigPayload> }) {
  const [values, setValues] = useState<Record<string, ConfigValue>>({});
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    setValues(config?.values ?? {});
  }, [config]);

  const groupedOptions = useMemo(() => {
    const groups = new Map<string, ConfigOption[]>();
    for (const option of config?.options ?? []) {
      const list = groups.get(option.category) ?? [];
      list.push(option);
      groups.set(option.category, list);
    }
    return [...groups.entries()];
  }, [config?.options]);

  const updateValue = (key: string, patch: Partial<ConfigValue>) => {
    const option = config?.options.find((item) => item.key === key);
    setValues((current) => {
      const existing = current[key] ?? { key, enabled: false, value: option?.default ?? "" };
      return { ...current, [key]: { ...existing, ...patch } };
    });
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!config) return;
    setSaving(true);
    setLocalError("");
    try {
      const payload = config.options.map((option) => values[option.key] ?? { key: option.key, enabled: false, value: option.default });
      const updated = await onSave(payload);
      setValues(updated.values);
    } catch (err) {
      setLocalError(normalizeError(err).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section>
      <div className="toolbar">
        <h1>Config</h1>
      </div>
      <form className="panel settingsPanel configSettingsPanel" onSubmit={submit}>
        <div className="formBuilderHeader">
          <LabelWithInfo text="Espanso default config" info="These settings are written to config/default.yml in your Espanso configuration folder. Disable an included setting to remove that key from default.yml." />
          <button className="primary" disabled={saving || !config} type="submit">
            {saving ? "Saving..." : "Save Config"}
          </button>
        </div>
        {localError && <div className="formError">{localError}</div>}
        <div className="settingsMeta">
          <span>Config path: {config?.status.config_path ?? "Not detected"}</span>
          <span>Default file: {config?.default_path ?? "Not detected"}</span>
        </div>
        {!config && <div className="empty compactEmpty">Loading config settings...</div>}
        {groupedOptions.map(([category, options]) => (
          <div className="configOptionGroup" key={category}>
            <h2>{category}</h2>
            <div className="configOptionGrid">
              {options.map((option) => {
                const current = values[option.key] ?? { key: option.key, enabled: false, value: option.default };
                return (
                  <div className={`configOptionCard ${current.enabled ? "enabled" : ""}`} key={option.key}>
                    <label className="checkRow configOptionToggle">
                      <input
                        type="checkbox"
                        checked={current.enabled}
                        onChange={(event) => updateValue(option.key, { enabled: event.target.checked })}
                      />
                      <span>{option.label}</span>
                      <InfoButton text={option.description} />
                    </label>
                    {renderConfigControl(option, current, (value) => updateValue(option.key, { value }))}
                    <code>{option.key}</code>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {config && Object.keys(config.unknown_values).length > 0 && (
          <div className="configOptionGroup">
            <h2>Manual YAML keys</h2>
            <p className="source">These keys are preserved by EspansoEdit but are not edited by this settings page.</p>
            <pre>{JSON.stringify(config.unknown_values, null, 2)}</pre>
          </div>
        )}
      </form>
      {config?.files.map((file) => (
        <div className="panel" key={file.path}>
          <h2>{file.file}</h2>
          <pre>{file.content}</pre>
        </div>
      ))}
      {config && config.files.length === 0 && <div className="empty">No config YAML files found.</div>}
    </section>
  );
}

function renderConfigControl(option: ConfigOption, current: ConfigValue, onChange: (value: unknown) => void) {
  const disabled = !current.enabled;
  if (option.type === "boolean") {
    return (
      <label className="checkboxLabel configBooleanControl">
        <input
          type="checkbox"
          disabled={disabled}
          checked={Boolean(current.value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>{Boolean(current.value) ? "Enabled" : "Disabled"}</span>
      </label>
    );
  }
  if (option.type === "number") {
    return (
      <input
        type="number"
        min={0}
        disabled={disabled}
        value={typeof current.value === "number" ? current.value : Number(option.default ?? 0)}
        onChange={(event) => onChange(event.target.value === "" ? 0 : Number(event.target.value))}
      />
    );
  }
  if (option.type === "select") {
    return (
      <select disabled={disabled} value={String(current.value ?? option.default ?? "")} onChange={(event) => onChange(event.target.value)}>
        {option.choices.map((choice) => (
          <option key={choice} value={choice}>{choice}</option>
        ))}
      </select>
    );
  }
  if (option.type === "list") {
    const listValue = Array.isArray(current.value) ? current.value.map((item) => String(item)).join("\n") : "";
    return (
      <textarea
        className="codeInput configListInput"
        disabled={disabled}
        value={listValue}
        onChange={(event) => onChange(event.target.value.split("\n"))}
        rows={4}
      />
    );
  }
  return (
    <input
      disabled={disabled}
      value={String(current.value ?? "")}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function Alert({
  type,
  title,
  message,
  details,
  onClose,
}: {
  type: "success" | "error";
  title: string;
  message: string;
  details?: unknown;
  onClose: () => void;
}) {
  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onClose();
    }
  };

  return (
    <div className={`alert ${type}`} role="button" tabIndex={0} onClick={onClose} onKeyDown={handleKeyDown}>
      <strong>{title}</strong>
      <span>{message}</span>
      {details ? <pre>{JSON.stringify(details, null, 2)}</pre> : null}
    </div>
  );
}

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return <span className={`pill ${ok ? "ok" : "warn"}`}>{label}</span>;
}

function normalizeError(err: unknown): ApiError {
  if (typeof err === "object" && err && "code" in err && "message" in err) return err as ApiError;
  return { code: "UNKNOWN_ERROR", message: "Unexpected error.", details: err };
}

function reloadMessage(reload: Record<string, unknown> | null) {
  const command = reload?.command;
  if (Array.isArray(command) && command.length === 0) return "Espanso will pick it up from its config watcher.";
  return "Espanso reload completed.";
}

function enabledSyncSourcesForFolder(settings: AppSettings | null, folder: string) {
  const target = folderKey(folder);
  return settings?.git_sync.sources.filter((source) => source.enabled && folderKey(source.folder) === target) ?? [];
}

function syncModeForFolder(settings: AppSettings | null, folder: string): SyncMode {
  const sources = enabledSyncSourcesForFolder(settings, folder);
  if (sources.some((source) => source.write_access)) return "two_way";
  if (sources.length > 0) return "one_way";
  return "none";
}

function syncModeForSource(source: GitSyncSource, validation?: GitSyncValidation): SyncMode {
  return validation?.write_access || source.write_access ? "two_way" : "one_way";
}

function syncSourceLabel(source: GitSyncSource, index: number) {
  if (source.name?.trim()) return source.name.trim();
  const repoPath = source.repo_url ? source.repo_url.trim().replace(/\/+$/, "").split("/").slice(-1)[0] : "";
  const repoName = repoPath.endsWith(".git") ? repoPath.slice(0, -4) : repoPath;
  return repoName || `Repository ${index + 1}`;
}

function gitBranchOptions(source: GitSyncSource, validation?: GitSyncValidation) {
  return Array.from(new Set([source.branch, validation?.branch, ...(validation?.branches ?? [])].filter((branch): branch is string => Boolean(branch?.trim()))));
}

function backupBranchOptions(settings: BackupSettings, validation?: BackupGitHubValidation) {
  return Array.from(new Set([settings.github_branch, validation?.branch, ...(validation?.branches ?? [])].filter((branch): branch is string => Boolean(branch?.trim()))));
}

function folderKey(folder: string | null | undefined) {
  const cleaned = (folder ?? "").trim().replace(/^\/+|\/+$/g, "");
  return !cleaned || cleaned.toLowerCase() === "root" ? "" : cleaned;
}

function encodeFolderPath(folder: string) {
  return folder.split("/").map(encodeURIComponent).join("/");
}

function downloadTextFile(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function saveTextFileWithBrowserPicker(filename: string, content: string, type: string): Promise<BrowserSaveResult> {
  if (!window.showDirectoryPicker) return "unsupported";
  try {
    const directory = await window.showDirectoryPicker({ mode: "readwrite" });
    const file = await directory.getFileHandle(filename, { create: true });
    const writable = await file.createWritable();
    await writable.write(new Blob([content], { type }));
    await writable.close();
    return "saved";
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return "cancelled";
    throw err;
  }
}

function handleCodeTextareaKeyDown(
  event: React.KeyboardEvent<HTMLTextAreaElement>,
  setValue: React.Dispatch<React.SetStateAction<string>>
) {
  if (event.key !== "Tab") return;
  event.preventDefault();

  const textarea = event.currentTarget;
  const value = textarea.value;
  const selectionStart = textarea.selectionStart;
  const selectionEnd = textarea.selectionEnd;
  const indent = "  ";
  const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;

  if (selectionStart !== selectionEnd) {
    const lineEnd = selectionEnd < value.length ? value.indexOf("\n", selectionEnd) : -1;
    const blockEnd = lineEnd === -1 ? value.length : lineEnd;
    const before = value.slice(0, lineStart);
    const block = value.slice(lineStart, blockEnd);
    const after = value.slice(blockEnd);

    if (event.shiftKey) {
      const lines = block.split("\n");
      let removedBeforeStart = 0;
      let removedTotal = 0;
      const nextBlock = lines.map((line, index) => {
        const removeCount = line.startsWith(indent) ? indent.length : line.startsWith(" ") ? 1 : 0;
        if (removeCount > 0) {
          removedTotal += removeCount;
          if (lineStart + lines.slice(0, index).join("\n").length + (index > 0 ? 1 : 0) < selectionStart) {
            removedBeforeStart += removeCount;
          }
          return line.slice(removeCount);
        }
        return line;
      }).join("\n");
      const nextValue = before + nextBlock + after;
      setValue(nextValue);
      requestAnimationFrame(() => {
        textarea.selectionStart = Math.max(lineStart, selectionStart - removedBeforeStart);
        textarea.selectionEnd = Math.max(textarea.selectionStart, selectionEnd - removedTotal);
      });
      return;
    }

    const nextBlock = block.split("\n").map((line) => indent + line).join("\n");
    const lineCount = block.split("\n").length;
    const nextValue = before + nextBlock + after;
    setValue(nextValue);
    requestAnimationFrame(() => {
      textarea.selectionStart = selectionStart + indent.length;
      textarea.selectionEnd = selectionEnd + indent.length * lineCount;
    });
    return;
  }

  if (event.shiftKey) {
    const linePrefix = value.slice(lineStart, selectionStart);
    const removeCount = linePrefix.endsWith(indent) ? indent.length : linePrefix.endsWith(" ") ? 1 : 0;
    if (removeCount === 0) return;
    const nextValue = value.slice(0, selectionStart - removeCount) + value.slice(selectionStart);
    setValue(nextValue);
    requestAnimationFrame(() => {
      textarea.selectionStart = selectionStart - removeCount;
      textarea.selectionEnd = selectionStart - removeCount;
    });
    return;
  }

  const nextValue = value.slice(0, selectionStart) + indent + value.slice(selectionEnd);
  setValue(nextValue);
  requestAnimationFrame(() => {
    textarea.selectionStart = selectionStart + indent.length;
    textarea.selectionEnd = selectionStart + indent.length;
  });
}

function toStructuredPayload(values: ShortcutFormValues) {
  return {
    trigger: values.trigger,
    replace: values.matchType === "replace" ? values.replace : "",
    form: values.matchType === "form" ? values.form : null,
    form_fields_yaml: values.matchType === "form" ? values.form_fields_yaml || null : null,
    folder: values.folder,
    label: values.label.trim() || null,
    word: values.word,
    propagate_case: values.propagate_case,
    case_insensitive: values.case_insensitive,
    uppercase_style: values.uppercase_style || null,
    force_mode: values.force_mode || null
  };
}

function toShortcutUpdatePayload(shortcut: Shortcut, patch: ShortcutOptionPatch) {
  const isForm = Boolean(shortcut.form);
  return {
    trigger: shortcut.trigger ?? "",
    replace: isForm ? "" : shortcut.replace ?? "",
    form: isForm ? shortcut.form : null,
    form_fields_yaml: isForm ? shortcut.form_fields_yaml || null : null,
    label: shortcut.label || null,
    word: patch.word ?? Boolean(shortcut.word),
    propagate_case: patch.propagate_case ?? Boolean(shortcut.propagate_case),
    case_insensitive: patch.case_insensitive ?? Boolean(shortcut.case_insensitive),
    uppercase_style: shortcut.uppercase_style || null,
    force_mode: shortcut.force_mode || null
  };
}

function sortShortcuts(shortcuts: Shortcut[], sortKey: ShortcutSortKey, direction: SortDirection) {
  const multiplier = direction === "asc" ? 1 : -1;
  return [...shortcuts].sort((a, b) => {
    const result = shortcutSortValue(a, sortKey).localeCompare(shortcutSortValue(b, sortKey), undefined, {
      numeric: true,
      sensitivity: "base"
    });
    if (result !== 0) return result * multiplier;
    return (a.trigger ?? "").localeCompare(b.trigger ?? "", undefined, { numeric: true, sensitivity: "base" });
  });
}

function shortcutSortValue(shortcut: Shortcut, sortKey: ShortcutSortKey) {
  if (sortKey === "trigger") return shortcut.trigger ?? "";
  if (sortKey === "replacement") return shortcut.replace ?? shortcut.form ?? "";
  if (sortKey === "source") return sourceLabel(shortcut);
  return shortcut.form ? "Form" : shortcut.supported ? "Structured" : "YAML";
}

function isBulkEditableShortcut(shortcut: Shortcut) {
  return shortcut.editable && shortcut.supported && Boolean(shortcut.trigger);
}

function sourceLabel(shortcut: Shortcut) {
  return shortcut.folder === "Root" ? shortcut.file : `${shortcut.folder}/${shortcut.file}`;
}

function macOSImportSourceLabel(preview: MacOSTextReplacementPreview) {
  const version = preview.macos_version ? `macOS ${preview.macos_version}` : "macOS";
  const source = preview.source_path ?? "preferences";
  const key = preview.source_key ? ` using ${preview.source_key}` : "";
  return `importable replacements selected from ${source}${key} on ${version}`;
}

function isImportableMacOSReplacement(item: MacOSTextReplacementItem) {
  return item.enabled && Boolean(item.trigger.trim()) && item.replacement !== "";
}

function defaultGitSyncSettings(): GitSyncSettings {
  return {
    enabled: false,
    sources: [defaultGitSyncSource()]
  };
}

function defaultBackupSettings(): BackupSettings {
  return {
    location: null,
    frequency: "always",
    github_enabled: false,
    github_repo_url: null,
    github_access_token: null,
    github_branch: null,
    github_path: "espansoedit-backups",
    last_synced_at: null,
    last_sync_message: null
  };
}

function normalizeAppSettings(settings: AppSettings): AppSettings {
  return {
    theme: settings.theme ?? "dark",
    git_sync: normalizeGitSyncSettings(settings.git_sync ?? defaultGitSyncSettings()),
    backup: normalizeBackupSettings(settings.backup ?? defaultBackupSettings())
  };
}

function normalizeBackupSettings(settings: BackupSettings): BackupSettings {
  const defaults = defaultBackupSettings();
  return {
    ...defaults,
    ...settings,
    location: settings.location?.trim() || null,
    github_repo_url: settings.github_repo_url?.trim() || null,
    github_access_token: settings.github_access_token?.trim() || null,
    github_branch: settings.github_branch?.trim() || null,
    github_path: settings.github_path?.trim() || defaults.github_path,
    last_synced_at: settings.last_synced_at?.trim() || null,
    last_sync_message: settings.last_sync_message?.trim() || null
  };
}

function defaultGitSyncSource(): GitSyncSource {
  return {
    id: `source-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    name: "",
    enabled: true,
    repo_url: "",
    access_token: "",
    branch: "",
    folder: "GitHub",
    write_access: false,
    file_paths: [],
    last_file_shas: {},
    last_local_hashes: {},
    installed_files: {},
    last_synced_at: null,
    last_sync_message: null
  };
}

function normalizeGitSyncSettings(settings: GitSyncSettings): GitSyncSettings {
  return {
    enabled: settings.enabled,
    sources: settings.sources.map(normalizeGitSyncSource)
  };
}

function normalizeGitSyncSource(source: GitSyncSource): GitSyncSource {
  return {
    ...source,
    name: source.name?.trim() || null,
    repo_url: source.repo_url?.trim() || null,
    access_token: source.access_token?.trim() || null,
    branch: source.branch?.trim() || null,
    folder: source.folder?.trim() || "GitHub",
    write_access: source.write_access,
    file_paths: source.file_paths.map((path) => path.trim()).filter(Boolean),
    last_local_hashes: source.last_local_hashes ?? {}
  };
}

function linesToFilePaths(text: string) {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

function createFormField(name = ""): FormFieldDraft {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    name,
    type: "text",
    values: ""
  };
}

function extractFormPlaceholders(template: string) {
  const names = new Set<string>();
  for (const match of template.matchAll(/\[\[([a-zA-Z0-9_-]+)\]\]/g)) {
    names.add(match[1]);
  }
  return [...names];
}

function validateFormTemplateFields(template: string, fieldsYaml: string) {
  const placeholders = extractFormPlaceholders(template);
  const definitions = parseFormFieldDefinitions(fieldsYaml);
  if (definitions.error) return { error: definitions.error, warning: "" };

  const fieldNames = new Set(definitions.fields.map((field) => field.name));
  const missing = placeholders.filter((name) => !fieldNames.has(name));
  if (missing.length > 0) {
    return {
      error: `Form fields YAML is missing ${listNames(missing)} used in the form template.`,
      warning: ""
    };
  }

  const placeholderNames = new Set(placeholders);
  const extra = definitions.fields.map((field) => field.name).filter((name) => !placeholderNames.has(name));
  return {
    error: "",
    warning: extra.length > 0 ? `Form fields YAML contains unused ${listNames(extra)}.` : ""
  };
}

function parseFormFieldDefinitions(text: string): { fields: FormFieldDraft[]; error: string } {
  const fields: FormFieldDraft[] = [];
  let current: FormFieldDraft | null = null;
  let readingValues = false;

  for (const rawLine of text.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    const fieldMatch = line.match(/^([A-Za-z0-9_-]+):\s*(\{\})?\s*$/);
    if (fieldMatch) {
      current = createFormField(fieldMatch[1]);
      fields.push(current);
      readingValues = false;
      continue;
    }
    const invalidTopLevel = line.match(/^([A-Za-z0-9_-]+):\s+.+$/);
    if (invalidTopLevel) {
      return { fields, error: `Form field ${invalidTopLevel[1]} must be a mapping.` };
    }
    if (!current) continue;
    const typeMatch = line.match(/^\s+type:\s*([A-Za-z0-9_-]+)\s*$/);
    if (typeMatch) {
      if (!["text", "choice", "list"].includes(typeMatch[1])) {
        return { fields, error: `Form field ${current.name} has unsupported type ${typeMatch[1]}.` };
      }
      current.type = typeMatch[1] as FormFieldType;
      readingValues = false;
      continue;
    }
    if (/^\s+multiline:\s*true\s*$/.test(line)) {
      current.type = "multiline";
      readingValues = false;
      continue;
    }
    if (/^\s+values:\s*$/.test(line)) {
      readingValues = true;
      continue;
    }
    const inlineValuesMatch = line.match(/^\s+values:\s*\[(.*)\]\s*$/);
    if (inlineValuesMatch) {
      current.values = inlineValuesMatch[1].split(",").map((value) => value.trim().replace(/^["']|["']$/g, "")).filter(Boolean).join("\n");
      readingValues = false;
      continue;
    }
    const valueMatch = line.match(/^\s+-\s*(.+)\s*$/);
    if (readingValues && valueMatch) {
      current.values = `${current.values}${current.values ? "\n" : ""}${valueMatch[1].replace(/^["']|["']$/g, "")}`;
    }
  }

  const invalidChoice = fields.find((field) => (field.type === "choice" || field.type === "list") && !field.values.trim());
  if (invalidChoice) {
    return { fields, error: `Form field ${invalidChoice.name} must include values.` };
  }
  return { fields, error: "" };
}

function listNames(names: string[]) {
  return names.map((name) => `[[${name}]]`).join(", ");
}

function buildFormFieldsYaml(fields: FormFieldDraft[]) {
  const validFields = fields.filter((field) => field.name.trim());
  return validFields.map((field) => buildFormFieldYaml(field)).join("");
}

function buildFormFieldYaml(field: FormFieldDraft) {
  const name = field.name.trim();
  const lines = [`${name}:`];
  if (field.type === "multiline") {
    lines.push("  type: text", "  multiline: true");
  } else {
    lines.push(`  type: ${field.type}`);
  }
  if (field.type === "choice" || field.type === "list") {
    const values = field.values.split("\n").map((value) => value.trim()).filter(Boolean);
    if (values.length > 0) {
      lines.push("  values:");
      for (const value of values) lines.push(`    - ${yamlScalar(value)}`);
    }
  }
  return `${lines.join("\n")}\n`;
}

function parseFormFieldsYaml(text: string): FormFieldDraft[] {
  const fields: FormFieldDraft[] = [];
  let current: FormFieldDraft | null = null;
  let readingValues = false;

  for (const line of text.split("\n")) {
    const fieldMatch = line.match(/^([A-Za-z0-9_-]+):\s*$/);
    if (fieldMatch) {
      current = createFormField(fieldMatch[1]);
      fields.push(current);
      readingValues = false;
      continue;
    }
    if (!current) continue;
    const typeMatch = line.match(/^\s+type:\s*(text|choice|list)\s*$/);
    if (typeMatch) {
      current.type = typeMatch[1] as FormFieldType;
      readingValues = false;
      continue;
    }
    if (/^\s+multiline:\s*true\s*$/.test(line)) {
      current.type = "multiline";
      readingValues = false;
      continue;
    }
    if (/^\s+values:\s*$/.test(line)) {
      readingValues = true;
      continue;
    }
    const valueMatch = line.match(/^\s+-\s*(.+)\s*$/);
    if (readingValues && valueMatch) {
      current.values = `${current.values}${current.values ? "\n" : ""}${valueMatch[1].replace(/^["']|["']$/g, "")}`;
    }
  }
  return fields;
}

function yamlScalar(value: string) {
  return /^[A-Za-z0-9 _.-]+$/.test(value) ? value : JSON.stringify(value);
}

function fileName(path: string) {
  return path.split("/").pop() ?? path;
}

type RootWindow = Window & {
  __espansoShortcutManagerRoot?: ReturnType<typeof createRoot>;
};

const rootWindow = window as RootWindow;
const root = rootWindow.__espansoShortcutManagerRoot ?? createRoot(document.getElementById("root")!);
rootWindow.__espansoShortcutManagerRoot = root;

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
