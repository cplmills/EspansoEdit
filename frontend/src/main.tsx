import React, { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type View = "shortcuts" | "config" | "health" | "backups";

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
  folder: string;
  raw_yaml: string;
  raw: boolean;
};

type FolderItem = {
  name: string;
  count: number;
};

const nav: { id: View; label: string }[] = [
  { id: "shortcuts", label: "Shortcuts" },
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
  const [config, setConfig] = useState<ConfigPayload | null>(null);
  const [search, setSearch] = useState("");
  const [selectedFolder, setSelectedFolder] = useState("All");
  const [editing, setEditing] = useState<Shortcut | "new" | null>(null);
  const [moving, setMoving] = useState<Shortcut | null>(null);
  const [creatingFolder, setCreatingFolder] = useState(false);
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

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">Espanso Shortcut Manager</div>
        <nav>
          {nav.map((item) => (
            <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}>
              {item.label}
            </button>
          ))}
        </nav>
      </aside>
      <main className="content">
        {error && <Alert type="error" title={error.code} message={error.message} details={error.details} />}
        {notice && <Alert type="success" title="Success" message={notice} />}
        {loading && <div className="loading">Loading...</div>}
        {view === "shortcuts" && (
          <ShortcutsView
            shortcuts={filtered}
            folders={folders}
            selectedFolder={selectedFolder}
            search={search}
            setSelectedFolder={setSelectedFolder}
            setSearch={setSearch}
            onAdd={() => setEditing("new")}
            onCreateFolder={() => setCreatingFolder(true)}
            onEdit={setEditing}
            onMove={setMoving}
            onDropShortcut={dropShortcut}
            onDelete={deleteShortcut}
          />
        )}
        {view === "health" && <HealthView status={status} onValidate={runValidation} />}
        {view === "backups" && <BackupsView backups={backups} onRestore={restore} />}
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
  folders: FolderItem[];
  selectedFolder: string;
  search: string;
  setSelectedFolder: (value: string) => void;
  setSearch: (value: string) => void;
  onAdd: () => void;
  onCreateFolder: () => void;
  onEdit: (shortcut: Shortcut) => void;
  onMove: (shortcut: Shortcut) => void;
  onDropShortcut: (shortcutId: string, folder: string) => void;
  onDelete: (shortcut: Shortcut) => void;
}) {
  const totalCount = props.folders.reduce((sum, folder) => sum + folder.count, 0);

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
      <div className="shortcutLayout">
        <div className="folderRail">
          <button className={props.selectedFolder === "All" ? "active" : ""} onClick={() => props.setSelectedFolder("All")}>
            <span>All</span>
            <strong>{totalCount}</strong>
          </button>
          {props.folders.map((folder) => (
            <button
              key={folder.name}
              className={props.selectedFolder === folder.name ? "active" : ""}
              onClick={() => props.setSelectedFolder(folder.name)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                const shortcutId = event.dataTransfer.getData("text/plain");
                if (shortcutId) props.onDropShortcut(shortcutId, folder.name);
              }}
            >
              <span>{folder.name}</span>
              <strong>{folder.count}</strong>
            </button>
          ))}
        </div>
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
              <strong>{shortcut.trigger ?? "Advanced entry"}</strong>
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
      </div>
    </section>
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
  const [matchType, setMatchType] = useState<"replace" | "form">(props.shortcut?.form ? "form" : "replace");
  const [label, setLabel] = useState(props.shortcut?.label ?? "");
  const [word, setWord] = useState(Boolean(props.shortcut?.word));
  const [propagateCase, setPropagateCase] = useState(Boolean(props.shortcut?.propagate_case));
  const [uppercaseStyle, setUppercaseStyle] = useState(props.shortcut?.uppercase_style ?? "");
  const [folder, setFolder] = useState(props.shortcut?.folder ?? props.initialFolder);
  const [rawYaml, setRawYaml] = useState(props.shortcut?.raw_yaml ?? "");
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");
  const raw = Boolean(props.shortcut && !props.shortcut.supported);

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
          <button type="button" onClick={props.onClose}>
            Close
          </button>
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
              <select value={matchType} onChange={(event) => setMatchType(event.target.value as "replace" | "form")}>
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
                  Form template
                  <textarea value={form} onChange={(event) => setForm(event.target.value)} rows={8} placeholder={"Hi [[name]],\n\nYour order [[order_id]] is ready."} />
                </label>
                <label>
                  Form fields YAML
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
          </>
        )}
        <button className="primary" disabled={saving} type="submit">
          {saving ? "Saving..." : "Save"}
        </button>
      </form>
    </div>
  );
}

function InfoButton({ text }: { text: string }) {
  return (
    <button className="infoButton" type="button" aria-label={text}>
      i
      <span className="tooltip" role="tooltip">{text}</span>
    </button>
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
  return (
    <>
      <input list="folder-options" value={props.value} onChange={(event) => props.onChange(event.target.value)} placeholder="Root or work/email" />
      <datalist id="folder-options">
        <option value="Root" />
        {props.folders.filter((folder) => folder.name !== "Root").map((folder) => (
          <option key={folder.name} value={folder.name} />
        ))}
      </datalist>
    </>
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
    uppercase_style: values.uppercase_style || null
  };
}

function sourceLabel(shortcut: Shortcut) {
  return shortcut.folder === "Root" ? shortcut.file : `${shortcut.folder}/${shortcut.file}`;
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
