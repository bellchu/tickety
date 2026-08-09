(function () {
  "use strict";

  var client;
  var sessionToken;
  var externalTicketId;
  var expectedUpdatedAt;

  function show(id) { document.getElementById(id).hidden = false; }
  function hide(id) { document.getElementById(id).hidden = true; }

  function fail(error) {
    hide("loading");
    var node = document.getElementById("error");
    node.textContent = error && error.message ? error.message : "Tickety could not establish a trusted embedded session.";
    show("error");
  }

  function parseTemplateResponse(result) {
    if (!result || result.status < 200 || result.status >= 300) {
      throw new Error("Tickety returned an unsuccessful response.");
    }
    try { return JSON.parse(result.response || "{}"); }
    catch (_error) { throw new Error("Tickety returned an invalid response."); }
  }

  function unwrap(data, key) {
    return data && data[key] !== undefined ? data[key] : data;
  }

  function accountHost(currentHost) {
    var endpoints = currentHost.endpoint_urls || {};
    var value = endpoints.freshservice || "";
    try { return new URL(value.indexOf("://") === -1 ? "https://" + value : value).hostname; }
    catch (_error) { return value; }
  }

  function workspaceId(currentHost, ticket) {
    if (ticket && ticket.workspace_id !== undefined && ticket.workspace_id !== null) {
      return String(ticket.workspace_id);
    }
    var workspace = currentHost.workspaces && currentHost.workspaces.freshservice;
    return workspace && workspace.id !== undefined ? String(workspace.id) : null;
  }

  async function establishSession(context) {
    var bootstrapResult = await client.request.invokeTemplate("ticketyBootstrap", {
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
    var bootstrap = parseTemplateResponse(bootstrapResult);
    var redeemResult = await client.request.invokeTemplate("ticketyRedeem", {
      body: JSON.stringify({ binding_id: context.bindingId, code: bootstrap.code })
    });
    return parseTemplateResponse(redeemResult);
  }

  function option(value, label) {
    var item = document.createElement("option");
    item.value = value;
    item.textContent = label || value;
    return item;
  }

  function populateSelect(id, values, selected) {
    var select = document.getElementById(id);
    select.replaceChildren();
    values.forEach(function (value) { select.appendChild(option(value)); });
    select.value = selected;
  }

  function renderResolution(value) {
    var root = document.getElementById("resolution");
    root.replaceChildren();
    var plan = value && (value.plan || value);
    if (!plan) {
      root.textContent = "No reviewed resolution is available yet.";
      return;
    }
    if (plan.root_cause_hypothesis) {
      var hypothesis = document.createElement("p");
      hypothesis.textContent = plan.root_cause_hypothesis;
      root.appendChild(hypothesis);
    }
    if (Array.isArray(plan.resolution_steps) && plan.resolution_steps.length) {
      var list = document.createElement("ol");
      plan.resolution_steps.forEach(function (step) {
        var item = document.createElement("li");
        item.textContent = String(step);
        list.appendChild(item);
      });
      root.appendChild(list);
    }
  }

  function renderTicket(context) {
    var ticket = context.ticket;
    externalTicketId = String(ticket.external_id);
    expectedUpdatedAt = ticket.updated_at;
    document.getElementById("environment").textContent = context.binding.environment;
    document.getElementById("subject").textContent = ticket.subject;
    document.getElementById("summary").textContent = ticket.summary || "No summary is available yet.";
    populateSelect("status", ["Open", "Pending", "Resolved", "Closed", "Escalated"], ticket.status);
    populateSelect("priority", ["P1", "P2", "P3", "P4"], ticket.priority);
    renderResolution(ticket.recommended_solution);
    var writeSupported =
      context.capabilities["ticket.update"] !== "unsupported" &&
      context.capabilities["freshworks.trusted_agent_identity"] === "supported";
    document.getElementById("save").disabled = !writeSupported;
    if (!writeSupported) {
      document.getElementById("write-status").textContent =
        "Write-back remains locked until agent identity and ticket updates are verified for this binding.";
    }
    hide("loading");
    show("ticket-panel");
  }

  async function loadTicket() {
    var result = await client.request.invokeTemplate("ticketyTicketContext", {
      context: { external_ticket_id: externalTicketId, session_token: sessionToken },
      cache: false
    });
    renderTicket(parseTemplateResponse(result));
  }

  async function saveTicket() {
    var button = document.getElementById("save");
    var statusNode = document.getElementById("write-status");
    button.disabled = true;
    statusNode.textContent = "Checking Freshservice version and writing changes…";
    try {
      var result = await client.request.invokeTemplate("ticketyTicketWriteback", {
        context: {
          external_ticket_id: externalTicketId,
          session_token: sessionToken,
          idempotency_key: crypto.randomUUID()
        },
        body: JSON.stringify({
          status: document.getElementById("status").value,
          priority: document.getElementById("priority").value,
          expected_updated_at: expectedUpdatedAt
        })
      });
      var response = parseTemplateResponse(result);
      expectedUpdatedAt = response.ticket.updated_at;
      statusNode.textContent = "Freshservice updated successfully.";
    } catch (error) {
      statusNode.textContent = error && error.message ? error.message : "Write-back failed. Refresh the ticket before retrying.";
    } finally {
      button.disabled = false;
    }
  }

  async function initialize() {
    try {
      client = await window.app.initialized();
      var values = await Promise.all([
        client.data.get("currentHost"),
        client.data.get("loggedInUser"),
        client.iparams.get()
      ]);
      var currentHost = unwrap(values[0], "currentHost");
      var loggedIn = unwrap(values[1], "loggedInUser");
      var agent = loggedIn.agent || loggedIn;
      var iparams = values[2] || {};
      var ticket = null;
      try { ticket = unwrap(await client.data.get("ticket"), "ticket"); }
      catch (_error) { ticket = null; }
      if (!agent || !agent.id || !iparams.binding_id) {
        throw new Error("Freshworks did not provide the required installation or agent context.");
      }
      var context = {
        currentHost: currentHost,
        host: accountHost(currentHost),
        agent: agent,
        bindingId: iparams.binding_id,
        ticket: ticket
      };
      var session = await establishSession(context);
      sessionToken = session.access_token;
      if (ticket) {
        externalTicketId = String(ticket.id);
        expectedUpdatedAt = ticket.updated_at;
        await loadTicket();
      } else {
        hide("loading");
        var details = document.getElementById("connection-details");
        [["Binding", session.binding_id], ["Session expires", session.expires_at]].forEach(function (entry) {
          var term = document.createElement("dt");
          var value = document.createElement("dd");
          term.textContent = entry[0];
          value.textContent = entry[1];
          details.appendChild(term);
          details.appendChild(value);
        });
        show("full-page");
      }
    } catch (error) { fail(error); }
  }

  document.getElementById("save").addEventListener("click", saveTicket);
  window.addEventListener("load", initialize);
}());
