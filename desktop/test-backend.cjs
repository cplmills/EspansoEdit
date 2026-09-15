const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");
const { spawn } = require("node:child_process");
const { once } = require("node:events");

async function main() {
  const root = path.resolve(__dirname, "..");
  const resources = process.argv[2] && path.resolve(process.argv[2]);
  const executable = resources
    ? path.join(resources, "backend", "espansoedit-backend")
    : path.join(root, "backend", "dist", "espansoedit-backend", "espansoedit-backend");
  const frontend = resources ? path.join(resources, "frontend") : path.join(root, "frontend", "dist");
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "espanso-install-check-"));
  const config = path.join(fixture, "config");
  const espanso = path.join(fixture, "espanso");
  fs.mkdirSync(config);
  fs.writeFileSync(espanso, '#!/bin/sh\ncase "$1" in\n  path) printf "%s\\n" "$ESPANSO_TEST_CONFIG" ;;\n  --version) echo "espanso test" ;;\n  status) echo "running" ;;\n  --help) echo "start stop status path" ;;\nesac\n', { mode: 0o755 });
  const server = net.createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));

  // Deny the dependencies that accidentally made earlier installers work on the build machine.
  const profile = `(version 1)(allow default)
    (deny file-read* (subpath "/Library/Frameworks/Python.framework")
      (subpath ${JSON.stringify(path.join(root, "backend", ".venv"))})
      (literal "/usr/bin/python3"))`;
  const env = { ...process.env, PATH: "/usr/bin:/bin", ESPANSO_EXECUTABLE: espanso,
    ESPANSO_TEST_CONFIG: config, ESPANSOEDIT_FRONTEND_DIR: frontend };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  const child = spawn("/usr/bin/sandbox-exec", ["-p", profile, executable, "--port", String(port)], { env, cwd: fixture });
  const exit = once(child, "exit");
  let log = "";
  child.stdout.on("data", chunk => { log += chunk; });
  child.stderr.on("data", chunk => { log += chunk; });
  const base = `http://127.0.0.1:${port}`;
  async function request(route, method = "GET", body) {
    const response = await fetch(base + route, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
    const result = await response.json();
    assert(response.ok, JSON.stringify(result));
    return result;
  }
  try {
    let ready = false;
    for (let attempt = 0; attempt < 450; attempt++) {
      if (child.exitCode !== null) throw new Error(log);
      try { ready = (await fetch(base)).ok; } catch {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, log || "Backend did not start");
    const settings = await request("/api/settings");
    assert.deepEqual(settings.git_sync.sources, []);
    const saved = await request("/api/settings", "PUT", { ...settings, theme: "light" });
    assert.equal(saved.theme, "light");
    const shortcut = await request("/api/shortcuts", "POST", { trigger: ":install-test", replace: "Clean install works" });
    assert.equal(shortcut.shortcut.replace, "Clean install works");
    const updated = await request(`/api/shortcuts/${shortcut.shortcut.id}/options`, "PATCH", { propagate_case: false });
    assert.equal(updated.shortcut.propagate_case, false);
    assert.equal((await request("/api/shortcuts")).length, 1);
    const ui = await fetch(base + "/ui/");
    assert(ui.ok);
    const html = await ui.text();
    const script = html.match(/src="([^"]+\.js)"/)[1];
    assert((await fetch(new URL(script, base + "/ui/"))).ok);
    assert(fs.existsSync(path.join(config, "match", "espanso-shortcut-manager.yml")));
    console.log("PASS: standalone backend, empty settings, save settings, create shortcut, bulk option, and same-origin UI assets; external Python access denied.");
  } catch (error) {
    console.error(log);
    throw error;
  } finally {
    if (child.exitCode === null) child.kill();
    await exit;
    fs.rmSync(fixture, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
