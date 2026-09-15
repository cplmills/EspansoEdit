const { test } = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const { once } = require("node:events");
const { requestBackend } = require("./backend-client.cjs");

async function serve(t, handler) {
  const server = http.createServer(handler);
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => new Promise(resolve => {
    server.closeAllConnections();
    server.close(resolve);
  }));
  return `http://127.0.0.1:${server.address().port}`;
}

test("forwards a shortcut save and returns its response", async t => {
  let calls = 0;
  const base = await serve(t, (request, response) => {
    calls++;
    assert.equal(request.url, "/api/shortcuts");
    assert.equal(request.method, "POST");
    let body = "";
    request.on("data", chunk => { body += chunk; });
    request.on("end", () => {
      assert.deepEqual(JSON.parse(body), { trigger: ":hello", replace: "Hello" });
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ success: true }));
    });
  });
  const result = await requestBackend(base, { path: "/api/shortcuts", method: "POST", body: JSON.stringify({ trigger: ":hello", replace: "Hello" }) }, {});
  assert.equal(result.ok, true);
  assert.deepEqual(result.payload, { success: true });
  assert.equal(calls, 1);
});

test("preserves backend validation errors", async t => {
  const error = { detail: { error: { code: "INVALID_TRIGGER", message: "Trigger cannot be empty." } } };
  const base = await serve(t, (_, response) => {
    response.writeHead(422);
    response.end(JSON.stringify(error));
  });
  const result = await requestBackend(base, { path: "/api/shortcuts" }, {});
  assert.equal(result.status, 422);
  assert.equal(result.ok, false);
  assert.deepEqual(result.payload, error);
});

test("rejects remote URLs and paths outside the API", async t => {
  let calls = 0;
  const base = await serve(t, () => { calls++; });
  for (const path of ["https://example.com/api/settings", "//example.com/api/settings", "/ui/", "/api/../ui/", "/api/%2e%2e/ui/", "/api/\\example.com"]) {
    const result = await requestBackend(base, { path }, {});
    assert.equal(result.payload.error.code, "INVALID_API_REQUEST", path);
  }
  assert.equal(calls, 0);
});

test("a dropped connection produces diagnostics without retrying a save", async t => {
  let calls = 0;
  const base = await serve(t, (request) => { calls++; request.socket.destroy(); });
  const result = await requestBackend(base, { path: "/api/settings", method: "PUT", body: '{"access_token":"secret"}' }, { app_version: "test", backend_running: true });
  assert.equal(result.payload.error.code, "BACKEND_UNAVAILABLE");
  assert.equal(result.payload.error.details.app_version, "test");
  assert.equal(calls, 1);
  assert(!JSON.stringify(result).includes("secret"));
});

test("reports timeouts and unreadable responses", async t => {
  const stalled = await serve(t, () => {});
  const timeout = await requestBackend(stalled, { path: "/api/settings" }, {}, 25);
  assert.equal(timeout.payload.error.code, "BACKEND_TIMEOUT");
  const malformed = await serve(t, (_, response) => response.end("Internal server error"));
  const result = await requestBackend(malformed, { path: "/api/settings" }, {});
  assert.equal(result.payload.error.code, "INVALID_BACKEND_RESPONSE");
});
