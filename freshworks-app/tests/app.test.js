const bindingId = "11111111-1111-4111-8111-111111111111";

function installDom() {
  document.body.innerHTML = `
    <section id="loading"></section>
    <section id="error" hidden></section>
    <section id="full-page" hidden><dl id="connection-details"></dl></section>
    <section id="ticket-panel" hidden>
      <span id="environment"></span>
      <h1 id="subject"></h1>
      <p id="summary"></p>
      <span id="status"></span>
      <span id="priority"></span>
      <div id="resolution"></div>
    </section>`;
}

function baseClient(ticket) {
  const data = {
    currentHost: {
      currentHost: {
        endpoint_urls: { freshservice: "https://trial-acme.freshservice.com" },
        workspaces: { freshservice: { id: 7 } }
      }
    },
    loggedInUser: { loggedInUser: { agent: { id: 42 } } },
    ticket: { ticket: ticket }
  };
  return {
    data: {
      get: vi.fn((key) => Promise.resolve(data[key]))
    },
    iparams: {
      get: vi.fn(() => Promise.resolve({ binding_id: bindingId }))
    },
    request: {
      invokeTemplate: vi.fn()
    }
  };
}

async function loadApp(client) {
  let loadHandler;
  vi.spyOn(window, "addEventListener").mockImplementation((event, handler) => {
    if (event === "load") loadHandler = handler;
  });
  window.app = { initialized: vi.fn(() => Promise.resolve(client)) };
  vi.resetModules();
  await import("../app/scripts/app.js");
  await loadHandler();
}

beforeEach(() => {
  installDom();
});

test("ticket sidebar creates a scoped session and renders read-only context", async () => {
  const client = baseClient({ id: 99, workspace_id: 7, updated_at: "2026-08-21T00:00:00Z" });
  client.request.invokeTemplate
    .mockResolvedValueOnce({ status: 201, response: JSON.stringify({ code: "single-use" }) })
    .mockResolvedValueOnce({ status: 200, response: JSON.stringify({ access_token: "short-lived" }) })
    .mockResolvedValueOnce({
      status: 200,
      response: JSON.stringify({
        binding: { environment: "trial" },
        ticket: {
          external_id: "99",
          subject: "Printer unavailable",
          summary: "Office printer is unreachable.",
          status: "Open",
          priority: "P2",
          recommended_solution: {
            plan: {
              root_cause_hypothesis: "The print service is offline.",
              resolution_steps: ["Restart the service", "Run a test page"]
            }
          }
        }
      })
    });

  await loadApp(client);

  expect(client.request.invokeTemplate.mock.calls.map((call) => call[0])).toEqual([
    "ticketyBootstrap",
    "ticketyRedeem",
    "ticketyTicketContext"
  ]);
  const bootstrapBody = JSON.parse(client.request.invokeTemplate.mock.calls[0][1].body);
  expect(bootstrapBody).toMatchObject({
    binding_id: bindingId,
    account_host: "trial-acme.freshservice.com",
    external_user_id: "42",
    workspace_id: "7",
    external_ticket_id: "99",
    audience: "ticket_sidebar"
  });
  expect(client.request.invokeTemplate.mock.calls[2][1]).toMatchObject({
    context: { external_ticket_id: "99", session_token: "short-lived" },
    cache: false
  });
  expect(document.getElementById("ticket-panel").hidden).toBe(false);
  expect(document.getElementById("subject").textContent).toBe("Printer unavailable");
  expect(document.querySelectorAll("#resolution li")).toHaveLength(2);
});

test("full page uses workspace context and contains no ticket mutation call", async () => {
  const client = baseClient(null);
  client.data.get.mockImplementation((key) => {
    if (key === "ticket") return Promise.reject(new Error("not available in full page"));
    const values = {
      currentHost: {
        currentHost: {
          endpoint_urls: { freshservice: "trial-acme.freshservice.com" },
          workspaces: { freshservice: { id: 7 } }
        }
      },
      loggedInUser: { loggedInUser: { id: 42 } }
    };
    return Promise.resolve(values[key]);
  });
  client.request.invokeTemplate
    .mockResolvedValueOnce({ status: 201, response: JSON.stringify({ code: "single-use" }) })
    .mockResolvedValueOnce({
      status: 200,
      response: JSON.stringify({
        access_token: "short-lived",
        binding_id: bindingId,
        expires_at: "2026-08-21T00:10:00Z"
      })
    });

  await loadApp(client);

  expect(client.request.invokeTemplate.mock.calls.map((call) => call[0])).toEqual([
    "ticketyBootstrap",
    "ticketyRedeem"
  ]);
  const body = JSON.parse(client.request.invokeTemplate.mock.calls[0][1].body);
  expect(body).toMatchObject({ workspace_id: "7", external_ticket_id: null, audience: "full_page_app" });
  expect(document.getElementById("full-page").hidden).toBe(false);
  expect(document.getElementById("connection-details").textContent).toContain(bindingId);
});

test("missing trusted agent context fails closed before any request", async () => {
  const client = baseClient(null);
  client.data.get.mockResolvedValueOnce({ currentHost: { endpoint_urls: {}, workspaces: {} } });
  client.data.get.mockResolvedValueOnce({ loggedInUser: {} });

  await loadApp(client);

  expect(client.request.invokeTemplate).not.toHaveBeenCalled();
  expect(document.getElementById("error").hidden).toBe(false);
  expect(document.getElementById("error").textContent).toContain("required installation or agent context");
});

test("unsuccessful and invalid Tickety responses fail closed", async () => {
  const client = baseClient({ id: 99 });
  client.request.invokeTemplate.mockResolvedValueOnce({ status: 403, response: "{}" });
  await loadApp(client);
  expect(document.getElementById("error").textContent).toBe("Tickety returned an unsuccessful response.");

  installDom();
  const invalidClient = baseClient({ id: 99 });
  invalidClient.request.invokeTemplate.mockResolvedValueOnce({ status: 201, response: "not-json" });
  await loadApp(invalidClient);
  expect(document.getElementById("error").textContent).toBe("Tickety returned an invalid response.");
});
