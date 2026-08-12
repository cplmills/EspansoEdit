import React, { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type View = "shortcuts" | "packages" | "config" | "health" | "backups";

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

type ConfigPayload = {
  status: Status;
  files: { path: string; file: string; content: string }[];
};

type MutationResult = {
  success: boolean;
  reload: Record<string, unknown> | null;
  shortcut?: Shortcut | null;
};

type ShortcutFormValues = {
  matchType: "replace" | "form";
  trigger: string;
  replace: string;
  form: string;
  form_fields_yaml: string;
  label: string;
  word: boolean;
  propagate_case: boolean;
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

const nav: { id: View; label: string }[] = [
  { id: "shortcuts", label: "Shortcuts" },
  { id: "packages", label: "Packages" },
  { id: "config", label: "Config" },
  { id: "health", label: "Health" },
  { id: "backups", label: "Backups" }
];

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
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
  const [search, setSearch] = useState("");
  const [selectedFolder, setSelectedFolder] = useState("All");
  const [editing, setEditing] = useState<Shortcut | "new" | null>(null);
  const [moving, setMoving] = useState<Shortcut | null>(null);
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextStatus, nextShortcuts] = await Promise.all([
        api<Status>("/api/status"),
        api<Shortcut[]>("/api/shortcuts")
      ]);
      const nextFolders = await api<string[]>("/api/folders");
      setStatus(nextStatus);
      setShortcuts(nextShortcuts);
      setFolderNames(nextFolders);
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
    if (view === "backups") {
      api<Backup[]>("/api/backups").then(setBackups).catch((err) => setError(normalizeError(err)));
    }
    if (view === "config") {
      api<ConfigPayload>("/api/config").then(setConfig).catch((err) => setError(normalizeError(err)));
    }
    if (view === "packages") {
      api<PackageItem[]>("/api/packages").then(setPackages).catch((err) => setError(normalizeError(err)));
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
        const result = await api<MutationResult>("/api/shortcuts", { method: "POST", body: JSON.stringify(toStructuredPayload(values)) });
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

  return (
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
            <nav>
              {nav.map((item) => (
                <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}>
                  {item.label}
                </button>
              ))}
            </nav>
            {view === "shortcuts" && (
              <FolderRail
                folders={folders}
                selectedFolder={selectedFolder}
                onSelect={setSelectedFolder}
                onDropShortcut={dropShortcut}
              />
            )}
          </>
        )}
      </aside>
      <main className="content">
        {error && <Alert type="error" title={error.code} message={error.message} details={error.details} />}
        {notice && <Alert type="success" title="Success" message={notice} />}
        {loading && <div className="loading">Loading...</div>}
        {view === "shortcuts" && (
          <ShortcutsView
            shortcuts={filtered}
            search={search}
            setSearch={setSearch}
            onAdd={() => setEditing("new")}
            onCreateFolder={() => setCreatingFolder(true)}
            onEdit={setEditing}
            onMove={setMoving}
            onDelete={deleteShortcut}
          />
        )}
        {view === "health" && <HealthView status={status} onValidate={runValidation} />}
        {view === "backups" && <BackupsView backups={backups} onRestore={restore} />}
        {view === "packages" && <PackagesView packages={packages} onInstall={installPackage} onUpdate={updatePackage} onRemove={removePackage} />}
        {view === "config" && <ConfigView config={config} />}
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
    </div>
  );
}

function ShortcutsView(props: {
  shortcuts: Shortcut[];
  search: string;
  setSearch: (value: string) => void;
  onAdd: () => void;
  onCreateFolder: () => void;
  onEdit: (shortcut: Shortcut) => void;
  onMove: (shortcut: Shortcut) => void;
  onDelete: (shortcut: Shortcut) => void;
}) {
  return (
    <section>
      <div className="toolbar">
        <h1>Shortcuts</h1>
        <div className="toolbarActions">
          <button onClick={props.onCreateFolder}>New Folder</button>
          <button className="primary" onClick={props.onAdd}>Add Shortcut</button>
        </div>
      </div>
      <input
        className="search"
        placeholder="Search trigger, replacement, or file"
        value={props.search}
        onChange={(event) => props.setSearch(event.target.value)}
      />
      <div className="table">
        <div className="row header">
          <span>Trigger</span>
          <span>Replacement</span>
          <span>Source</span>
          <span>Status</span>
          <span></span>
        </div>
        {props.shortcuts.map((shortcut) => (
          <div
            className="row"
            key={shortcut.id}
            draggable={Boolean(shortcut.raw_yaml)}
            onDragStart={(event) => {
              event.dataTransfer.setData("text/plain", shortcut.id);
              event.dataTransfer.effectAllowed = "move";
            }}
          >
            <strong className="triggerText">{shortcut.trigger ?? "Advanced entry"}</strong>
            <span className="preview">{shortcut.replace ?? shortcut.form ?? "Unsupported match type"}</span>
            <span>{sourceLabel(shortcut)}</span>
            <StatusPill ok={shortcut.supported} label={shortcut.form ? "Form" : shortcut.supported ? "Structured" : "YAML"} />
            <span className="actions">
              <button disabled={!shortcut.editable && !shortcut.raw_yaml} onClick={() => props.onEdit(shortcut)}>
                Edit
              </button>
              <button disabled={!shortcut.raw_yaml} onClick={() => props.onMove(shortcut)}>
                Move
              </button>
              <button disabled={!shortcut.editable} onClick={() => props.onDelete(shortcut)}>
                Delete
              </button>
            </span>
          </div>
        ))}
        {props.shortcuts.length === 0 && <div className="empty">No shortcuts found.</div>}
      </div>
    </section>
  );
}

function FolderRail(props: {
  folders: FolderItem[];
  selectedFolder: string;
  onSelect: (folder: string) => void;
  onDropShortcut: (shortcutId: string, folder: string) => void;
}) {
  const totalCount = props.folders.reduce((sum, folder) => sum + folder.count, 0);

  const dropOnFolder = (event: React.DragEvent<HTMLButtonElement>, folder: string) => {
    event.preventDefault();
    const shortcutId = event.dataTransfer.getData("text/plain");
    if (shortcutId) props.onDropShortcut(shortcutId, folder);
  };

  return (
    <div className="sidebarSection">
      <div className="sidebarSectionTitle">Folders</div>
      <div className="folderRail">
        <button className={props.selectedFolder === "All" ? "active" : ""} onClick={() => props.onSelect("All")}>
          <span>All</span>
          <strong>{totalCount}</strong>
        </button>
        {props.folders.map((folder) => (
          <button
            key={folder.name}
            className={props.selectedFolder === folder.name ? "active" : ""}
            onClick={() => props.onSelect(folder.name)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => dropOnFolder(event, folder.name)}
          >
            <span>{folder.name}</span>
            <strong>{folder.count}</strong>
          </button>
        ))}
      </div>
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
  const [matchType, setMatchType] = useState<"replace" | "form">(props.shortcut?.form ? "form" : "replace");
  const [label, setLabel] = useState(props.shortcut?.label ?? "");
  const [word, setWord] = useState(Boolean(props.shortcut?.word));
  const [propagateCase, setPropagateCase] = useState(Boolean(props.shortcut?.propagate_case));
  const [uppercaseStyle, setUppercaseStyle] = useState(props.shortcut?.uppercase_style ?? "");
  const [forceMode, setForceMode] = useState(props.shortcut?.force_mode ?? "");
  const [folder, setFolder] = useState(props.shortcut?.folder ?? props.initialFolder);
  const [rawYaml, setRawYaml] = useState(props.shortcut?.raw_yaml ?? "");
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");
  const raw = Boolean(props.shortcut && !props.shortcut.supported);

  const changeMatchType = (nextType: "replace" | "form") => {
    if (nextType === "form" && !form && replace) setForm(replace);
    if (nextType === "replace" && !replace && form) setReplace(form);
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
        {raw ? (
          <label>
            Match YAML
            <textarea className="codeInput" value={rawYaml} onChange={(event) => setRawYaml(event.target.value)} rows={14} />
          </label>
        ) : (
          <>
            <label>
              Folder
              <FolderInput value={folder} folders={props.folders} onChange={setFolder} />
            </label>
            <label>
              Match type
              <select value={matchType} onChange={(event) => changeMatchType(event.target.value as "replace" | "form")}>
                <option value="replace">Text replacement</option>
                <option value="form">Form</option>
              </select>
            </label>
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
                  <textarea className="codeInput compactCodeInput" value={formFieldsYaml} onChange={(event) => setFormFieldsYaml(event.target.value)} rows={7} placeholder={"name:\n  type: text\norder_id:\n  type: text"} />
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

function InfoButton({ text }: { text: string }) {
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  const show = (target: HTMLElement) => {
    const rect = target.getBoundingClientRect();
    const tooltipWidth = Math.min(320, window.innerWidth - 32);
    const left = Math.min(Math.max(16, rect.left + rect.width / 2 - tooltipWidth / 2), window.innerWidth - tooltipWidth - 16);
    const top = Math.min(rect.bottom + 8, window.innerHeight - 180);
    setPosition({ left, top });
  };

  return (
    <>
      <button
        className="infoButton"
        type="button"
        aria-label={text}
        onBlur={() => setPosition(null)}
        onFocus={(event) => show(event.currentTarget)}
        onMouseEnter={(event) => show(event.currentTarget)}
        onMouseLeave={() => setPosition(null)}
      >
        i
      </button>
      {position && (
        <span className="tooltip visibleTooltip" role="tooltip" style={{ left: position.left, top: position.top }}>
          {text}
        </span>
      )}
    </>
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

function BackupsView({ backups, onRestore }: { backups: Backup[]; onRestore: (backup: Backup) => void }) {
  return (
    <section>
      <h1>Backups</h1>
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
            <button onClick={() => onRestore(backup)}>Restore</button>
          </div>
        ))}
        {backups.length === 0 && <div className="empty">No backups found.</div>}
      </div>
    </section>
  );
}

function ConfigView({ config }: { config: ConfigPayload | null }) {
  return (
    <section>
      <h1>Config</h1>
      <div className="panel">
        <p><strong>Config path:</strong> {config?.status.config_path ?? "Not detected"}</p>
        <p><strong>Config directory:</strong> {config?.status.config_dir ?? "Not detected"}</p>
        <p><strong>Validation:</strong> {config?.status.yaml_valid ? "Valid" : "Check required"}</p>
      </div>
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

function Alert({ type, title, message, details }: { type: "success" | "error"; title: string; message: string; details?: unknown }) {
  return (
    <div className={`alert ${type}`}>
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
    uppercase_style: values.uppercase_style || null,
    force_mode: values.force_mode || null
  };
}

function sourceLabel(shortcut: Shortcut) {
  return shortcut.folder === "Root" ? shortcut.file : `${shortcut.folder}/${shortcut.file}`;
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
