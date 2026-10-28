"use strict";

const state = {
  sessionId: crypto.randomUUID(),
  streaming: false,
};

const $ = (id) => document.getElementById(id);
const els = {
  form: $("chat-form"),
  query: $("query"),
  send: $("send"),
  reset: $("reset"),
  messages: $("messages"),
  traceList: $("trace-list"),
  citationList: $("citation-list"),
  metrics: $("metrics"),
  error: $("error-banner"),
  healthStatus: $("health-status"),
  routingBody: document.querySelector("#routing-table tbody"),
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

// ---------- health + routing table ----------

async function loadHealth() {
  try {
    const response = await fetch("/health");
    const body = await response.json();
    els.healthStatus.textContent = body.status;
    els.healthStatus.className = "pill " + (body.status === "ok" ? "ok" : "degraded");
    els.healthStatus.title = JSON.stringify(body.components, null, 2);
    els.routingBody.replaceChildren();
    for (const row of body.routing || []) {
      const tr = el("tr");
      for (const key of ["agent", "provider", "model", "dimension", "reason", "fallback", "backup"]) {
        tr.appendChild(el("td", null, row[key] ?? "—"));
      }
      els.routingBody.appendChild(tr);
    }
  } catch (err) {
    els.healthStatus.textContent = "unreachable";
    els.healthStatus.className = "pill degraded";
  }
}

// ---------- per-turn rendering ----------

function newTurn(query) {
  const turn = el("article", "turn");
  turn.appendChild(el("div", "user-msg", query));
  const card = el("div", "route-card");
  card.appendChild(el("div", "route-muted route-placeholder", "Supervisor planning…"));
  turn.appendChild(card);
  const answer = el("div", "answer");
  turn.appendChild(answer);
  els.messages.appendChild(turn);
  turn.scrollIntoView({ block: "end" });
  return { card, answer, text: "", routeCount: 0 };
}

function renderAnswer(turn) {
  // Rebuild the answer from plain text; [S#] markers become anchors to the citation panel.
  turn.answer.replaceChildren();
  const parts = turn.text.split(/(\[S\d+\])/g);
  for (const part of parts) {
    const match = /^\[(S\d+)\]$/.exec(part);
    if (match) {
      const link = document.createElement("a");
      link.href = "#cite-" + match[1];
      link.className = "cite-link";
      link.textContent = part;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        const target = document.getElementById("cite-" + match[1]);
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
          target.classList.add("flash");
          setTimeout(() => target.classList.remove("flash"), 1200);
        }
      });
      turn.answer.appendChild(link);
    } else if (part) {
      turn.answer.appendChild(document.createTextNode(part));
    }
  }
}

function updateRouteCard(turn, data) {
  if (data.kind === "agent_route") {
    // Supervisor llm_route rows arrive before the plan, so put the plan on top instead of clearing them.
    const placeholder = turn.card.querySelector(".route-placeholder");
    if (placeholder) placeholder.remove();
    const head = el("div", "route-head");
    head.appendChild(el("span", "tag category", data.category));
    head.appendChild(el("span", "route-plan", "plan: " + (data.plan.length ? data.plan.join(" → ") : "(none)")));
    head.appendChild(el("span", "route-muted", "planner: " + data.planner));
    turn.card.prepend(head, el("div", "route-reason", data.reason));
  } else if (data.kind === "llm_route") {
    const row = el("div", "route-llm" + (data.fallback ? " fallback" : ""));
    row.appendChild(el("span", "tag node", data.node));
    row.appendChild(el("span", "route-provider", data.provider + " / " + data.model));
    row.appendChild(el("span", "tag dim", data.dimension));
    if (data.fallback) row.appendChild(el("span", "tag warn", data.tier === 2 ? "BACKUP" : "FALLBACK"));
    row.appendChild(el("span", "route-muted", data.reason));
    turn.card.appendChild(row);
  } else if (data.kind === "transition" && data.node === "dispatch" && data.reason === "off-topic, no worker") {
    turn.card.appendChild(el("div", "route-muted", "off-topic, no worker"));
  }
}

function traceSummary(data) {
  switch (data.kind) {
    case "agent_route":
      return `${data.category} · plan [${(data.plan || []).join(", ")}] · ${data.reason}`;
    case "transition":
      return (data.next ? `→ ${data.next} · ` : "") + data.reason;
    case "llm_route":
      return `${data.provider}/${data.model} (${data.dimension})` +
        `${data.fallback ? (data.tier === 2 ? " BACKUP" : " FALLBACK") : ""} · ${data.reason}`;
    case "llm_done":
      return `${data.provider} ${data.elapsed_ms} ms · in ${data.input_tokens} / out ${data.output_tokens} tokens`;
    case "rag_retrieval":
      return `${(data.chunks || []).map((c) => `${c.id} (${c.score})`).join(", ") || "no chunks"} · ${data.web_reason}`;
    case "mcp_tool_call":
      return `${data.tool} ok=${data.ok}` + (data.ok ? ` results=${data.results}` : ` error=${data.error}`) +
        ` · ${data.elapsed_ms} ms`;
    case "sql_query":
      return `${data.sql}` + (data.ok ? ` · rows=${data.row_count}` : ` · error=${data.error}`);
    case "worker_error":
      return data.error;
    default:
      return "";
  }
}

function addTrace(data) {
  const item = el("li", "trace-item");
  const head = el("div", "trace-head");
  head.appendChild(el("span", "badge " + data.kind, data.kind));
  head.appendChild(el("span", "trace-node", data.node));
  head.appendChild(el("span", "trace-summary", traceSummary(data)));
  const detail = el("pre", "trace-detail", JSON.stringify(data, null, 2));
  detail.hidden = true;
  head.addEventListener("click", () => { detail.hidden = !detail.hidden; });
  item.appendChild(head);
  item.appendChild(detail);
  els.traceList.appendChild(item);
  item.scrollIntoView({ block: "nearest" });
}

function addCitation(data) {
  const item = el("li", "citation-item");
  item.id = "cite-" + data.label;
  const head = el("div", "citation-head");
  head.appendChild(el("span", "cite-label", "[" + data.label + "]"));
  head.appendChild(el("span", "tag " + data.kind, data.kind));
  head.appendChild(el("span", "cite-title", data.title + (data.page ? `, p.${data.page}` : "")));
  item.appendChild(head);
  if (data.kind === "sql") {
    item.appendChild(el("code", "cite-sql", data.snippet));
  } else {
    if (data.url) {
      const link = document.createElement("a");
      link.href = data.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = data.kind === "rag" ? data.ref : data.url;
      item.appendChild(link);
    }
    item.appendChild(el("div", "cite-snippet", data.snippet));
  }
  els.citationList.appendChild(item);
}

function showError(message) {
  els.error.textContent = message;
  els.error.hidden = false;
}

// ---------- SSE over fetch ----------

function parseFrame(block) {
  let event = "message";
  const dataLines = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  return { event, data: JSON.parse(dataLines.join("\n")) };
}

function handleEvent(turn, event, data) {
  if (event === "token") {
    turn.text += data.text;
    renderAnswer(turn);
  } else if (event === "trace") {
    addTrace(data);
    updateRouteCard(turn, data);
  } else if (event === "citation") {
    addCitation(data);
  } else if (event === "error") {
    showError(data.message);
  } else if (event === "done") {
    els.metrics.textContent =
      `elapsed ${data.elapsed_ms} ms · TTFT ${data.ttft_ms ?? "n/a"} ms · request ${data.request_id}`;
  }
}

async function ask(query) {
  if (state.streaming) return;
  state.streaming = true;
  els.send.disabled = true;
  els.error.hidden = true;
  els.traceList.replaceChildren();
  els.citationList.replaceChildren();
  els.metrics.textContent = "";
  const turn = newTurn(query);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, session_id: state.sessionId }),
    });
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try { detail += ": " + JSON.stringify((await response.json()).detail); } catch (_) { /* not JSON */ }
      showError(detail);
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index;
      while ((index = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        const frame = parseFrame(block);
        if (frame) handleEvent(turn, frame.event, frame.data);
      }
    }
  } catch (err) {
    showError("Connection error: " + err.message);
  } finally {
    state.streaming = false;
    els.send.disabled = false;
  }
}

// ---------- wiring ----------

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = els.query.value.trim();
  if (!query) return;
  els.query.value = "";
  ask(query);
});

els.query.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    els.form.requestSubmit();
  }
});

els.reset.addEventListener("click", () => {
  if (state.streaming) return;
  state.sessionId = crypto.randomUUID();
  els.messages.replaceChildren();
  els.traceList.replaceChildren();
  els.citationList.replaceChildren();
  els.metrics.textContent = "";
  els.error.hidden = true;
});

for (const button of document.querySelectorAll("#examples button")) {
  button.addEventListener("click", () => ask(button.dataset.q));
}

loadHealth();
