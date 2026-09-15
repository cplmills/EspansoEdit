const http = require("node:http");

function requestBackend(baseUrl, request, diagnostics, timeoutMs = 120000) {
  const failure = (code, message, details = {}) => ({
    ok: false, status: 0, statusText: message,
    payload: { error: { code, message, details: { ...diagnostics, ...details } } }
  });
  const method = request?.method || "GET";
  const requestPath = request?.path;
  let url;
  try {
    if (typeof requestPath !== "string" || !requestPath.startsWith("/api/") || requestPath.includes("\\")) throw new Error();
    url = new URL(requestPath, baseUrl);
    if (url.origin !== baseUrl || !url.pathname.startsWith("/api/")) throw new Error();
    if (!["GET", "POST", "PUT", "PATCH", "DELETE"].includes(method)) throw new Error();
    if (request.body !== undefined && typeof request.body !== "string") throw new Error();
  } catch {
    return Promise.resolve(failure("INVALID_API_REQUEST", "The app could not send this request."));
  }

  return new Promise((resolve) => {
    const connectionFailure = (error) => resolve(failure(
      "BACKEND_UNAVAILABLE",
      "EspansoEdit could not connect to its local service. Quit EspansoEdit completely and reopen it.",
      { request: `${method} ${url.pathname}`, reason: error.code || error.message }
    ));
    const connection = http.request(url, { method, headers: { "Content-Type": "application/json" } }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { body += chunk; });
      response.on("error", connectionFailure);
      response.on("end", () => {
        let payload;
        try { payload = JSON.parse(body); }
        catch {
          resolve(failure("INVALID_BACKEND_RESPONSE", "The local service returned an unreadable response.", { status: response.statusCode, request: `${method} ${url.pathname}` }));
          return;
        }
        resolve({ ok: response.statusCode >= 200 && response.statusCode < 300, status: response.statusCode, statusText: response.statusMessage, payload });
      });
    });
    connection.on("error", connectionFailure);
    connection.setTimeout(timeoutMs, () => {
      resolve(failure("BACKEND_TIMEOUT", "The local service took too long to respond. Check whether your change was saved before trying again.", { request: `${method} ${url.pathname}` }));
      connection.destroy();
    });
    connection.end(request.body);
  });
}

module.exports = { requestBackend };
