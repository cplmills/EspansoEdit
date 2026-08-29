# Espanso Shortcut Manager

Espanso Shortcut Manager is a local-first macOS web application for managing basic Espanso text-replacement shortcuts without manually editing YAML files.

The app has a FastAPI backend and a React/TypeScript frontend. It only binds to `127.0.0.1` during development and does not include authentication, cloud sync, user accounts, or remote hosting.

## Architecture

```text
backend/
  app/
    api/        REST API routes
    models/     Pydantic schemas
    services/   Espanso discovery, YAML parsing, safe writes, backups, reloads
    utils/      shared helpers and error types
  tests/        pytest coverage for safety-critical behavior
frontend/
  src/          React app
```

## Prerequisites

- macOS
- Python 3.10+
- Node.js 20.19+ or 22.12+ for the current Vite toolchain
- Espanso installed for full local use

The backend uses the Espanso CLI where possible, then falls back to known macOS Espanso configuration locations.

## Backend Development

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```

## Frontend Development

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` requests to `http://127.0.0.1:8765`.

## Mac Desktop App

The project also includes an Electron shell that packages the existing React UI with the FastAPI backend.

Install the desktop tooling once from the repo root:

```bash
npm install
```

Run the app from source:

```bash
npm run desktop:dev
```

Build a local unsigned macOS `.app` bundle:

```bash
npm run desktop:pack
```

Build a local unsigned DMG:

```bash
npm run desktop:dmg
```

The generated app is written to:

```text
release/mac-arm64/EspansoEdit.app
```

The generated DMG is written to:

```text
release/EspansoEdit-2.0.1-arm64.dmg
```

The desktop app starts the backend on `127.0.0.1:8765`, loads the built frontend, and adds a macOS menu bar/tray item with quick actions for opening the app and the Espanso match folder. Local development builds are unsigned; use a Developer ID certificate and notarization before distributing outside this Mac.

## Espanso Configuration Handling

On startup, the backend detects:

- whether `espanso` is available
- Espanso version
- whether Espanso appears to be running
- base config directory
- match directory
- config directory

The app reads `.yml` and `.yaml` files under the detected match directory. Version 1 fully supports entries shaped like:

```yaml
matches:
  - trigger: ":hello"
    replace: "Hello world"
```

Multiline `replace` values are supported. Advanced entries are displayed as unsupported/read-only and are preserved.

New shortcuts are written to:

```text
match/espanso-shortcut-manager.yml
```

Existing simple shortcuts in other match files can be edited in place. The app does not migrate existing shortcuts automatically.

## Safety Guarantees

Every modification uses a safe write workflow:

1. Read and parse the current file.
2. Apply the change in memory.
3. Validate the proposed YAML and Espanso match structure.
4. Reject duplicate triggers.
5. Write and re-parse a temporary file.
6. Create a timestamped backup.
7. Atomically replace the live file.
8. Reload Espanso.
9. Roll back and reload again if the reload fails.

The backend validates file paths and only permits writes inside the detected Espanso directories. Backups are stored outside the match directory so Espanso does not load them as match files.

## Backups

Backups are stored under:

```text
<espanso-config-dir>/shortcut-manager-backups/
```

Each backup includes:

- the original YAML file
- `metadata.json` with original path, backup path, timestamp, and operation

Backups can be listed and restored through the UI. Restoring a backup also creates a backup of the current live file before replacing it.

## Known Version 1 Limitations

- Unsupported Espanso match types are read-only.
- The Config screen is read-only.
- Reload behavior depends on installed Espanso CLI support.
- YAML comments and ordering are preserved where `ruamel.yaml` can preserve them.
- Manual macOS testing is still recommended against real Espanso installations.

## Tests

```bash
cd backend
pytest
```

The backend test suite covers loading, multiline replacements, CRUD operations, unrelated YAML preservation, unsupported entry preservation, duplicate detection, invalid YAML rejection, backup creation, reload rollback, and path traversal protection.
