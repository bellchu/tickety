(function () {
  "use strict";

  function show(id) { document.getElementById(id).hidden = false; }
  function hide(id) { document.getElementById(id).hidden = true; }

  function fail(error) {
    hide("loading");
    const node = document.getElementById("error");
    node.textContent = error && error.message ? error.message : "Tickety OPS Tower could not establish a trusted embedded session.";
    show("error");
  }

  function parseTemplateResponse(result) {
    if (!result || result.status < 200 || result.status >= 300) {
      throw new Error("Tickety OPS Tower returned an unsuccessful response.");
    }
    try { return JSON.parse(result.response || "{}"); }
    catch { throw new Error("Tickety OPS Tower returned an invalid response."); }
  }

  function unwrap(data, key) {
    return data && data[key] !== undefined ? data[key] : data;
  }

  function accountHost(currentHost) {
    const endpoints = currentHost.endpoint_urls || {};
    const value = endpoints.freshservice || "";
    try { return new URL(value.indexOf("://") === -1 ? "https://" + value : value).hostname; }
    catch { return value; }
  }

  function workspaceId(currentHost, ticket) {
    if (ticket && ticket.workspace_id !== undefined && ticket.workspace_id !== null) {
      return String(ticket.workspace_id);
    }
    const workspace = currentHost.workspaces && currentHost.workspaces.freshservice;
    return workspace && workspace.id !== undefined ? String(workspace.id) : null;
  }

  async function establishSession(client, context) {
    const bootstrapResult = await client.request.invokeTemplate("ticketyBootstrap", {
      body: JSON.stringify({
        binding_id: context.bindingId,
        account_host: context.host,
        external_user_id: String(context.agent.id),
        workspace_id: workspaceId(context.currentHost, context.ticket),
        external_ticket_id: context.ticket ? String(context.ticket.id) : null,
        ticket_updated_at: context.ticket ? context.ticket.updated_at : null,
        audience: context.ticket ? "ticket_sidebar" : "full_page_app"
      })
    });
    const bootstrap = parseTemplateResponse(bootstrapResult);
    const redeemResult = await client.request.invokeTemplate("ticketyRedeem", {
      body: JSON.stringify({ binding_id: context.bindingId, code: bootstrap.code })
    });
    return parseTemplateResponse(redeemResult);
  }

  function renderResolution(value) {
    const root = document.getElementById("resolution");
    root.replaceChildren();
    const plan = value && (value.plan || value);
    if (!plan) {
      root.textContent = "No reviewed recommendation is available yet.";
      return;
    }
    if (plan.root_cause_hypothesis) {
      const hypothesis = document.createElement("p");
      hypothesis.textContent = plan.root_cause_hypothesis;
      root.appendChild(hypothesis);
    }
    if (Array.isArray(plan.resolution_steps) && plan.resolution_steps.length) {
      const list = document.createElement("ol");
      plan.resolution_steps.forEach(function (step) {
        const item = document.createElement("li");
        item.textContent = String(step);
        list.appendChild(item);
      });
      root.appendChild(list);
    }
  }

  function renderTicket(context) {
    const ticket = context.ticket;
    document.getElementById("environment").textContent = context.binding.environment;
    document.getElementById("subject").textContent = ticket.subject;
    document.getElementById("summary").textContent = ticket.summary || "No summary is available yet.";
    document.getElementById("status").textContent = ticket.status;
    document.getElementById("priority").textContent = ticket.priority;
    renderResolution(ticket.recommended_solution);
    hide("loading");
    show("ticket-panel");
  }

  async function loadTicket(client, externalTicketId, sessionToken) {
    const result = await client.request.invokeTemplate("ticketyTicketContext", {
      context: { external_ticket_id: externalTicketId, session_token: sessionToken },
      cache: false
    });
    renderTicket(parseTemplateResponse(result));
  }

  async function readOptionalTicket(client) {
    try { return unwrap(await client.data.get("ticket"), "ticket"); }
    catch { return null; }
  }

  async function buildContext(client) {
    const values = await Promise.all([
      client.data.get("currentHost"),
      client.data.get("loggedInUser"),
      client.iparams.get()
    ]);
    const currentHost = unwrap(values[0], "currentHost");
    const loggedIn = unwrap(values[1], "loggedInUser");
    const agent = loggedIn.agent || loggedIn;
    const iparams = values[2] || {};
    const ticket = await readOptionalTicket(client);
    if (!agent || !agent.id || !iparams.binding_id) {
      throw new Error("Freshworks did not provide the required installation or agent context.");
    }
    return {
      currentHost: currentHost,
      host: accountHost(currentHost),
      agent: agent,
      bindingId: iparams.binding_id,
      ticket: ticket
    };
  }

  function renderConnection(session) {
    hide("loading");
    const details = document.getElementById("connection-details");
    [["Binding", session.binding_id], ["Session expires", session.expires_at]].forEach(function (entry) {
      const term = document.createElement("dt");
      const value = document.createElement("dd");
      term.textContent = entry[0];
      value.textContent = entry[1];
      details.appendChild(term);
      details.appendChild(value);
    });
    show("full-page");
  }

  async function initialize() {
    try {
      const client = await window.app.initialized();
      const context = await buildContext(client);
      const session = await establishSession(client, context);
      if (!context.ticket) {
        renderConnection(session);
        return;
      }
      await loadTicket(
        client,
        String(context.ticket.id),
        session.access_token
      );
    } catch (error) { fail(error); }
  }

  window.addEventListener("load", initialize);
}());
