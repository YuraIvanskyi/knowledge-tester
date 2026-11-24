// Live counters and takers table for the teacher share screen (polls every 5 s, 3 s in
// presentation mode), and a short note with the name of everyone who has just handed in.
(function () {
  "use strict";
  var root = document.getElementById("share");
  if (!root || !window.fetch) return;
  var url = root.getAttribute("data-stats-url");
  var pollMs = parseInt(root.getAttribute("data-poll"), 10) || 5000;
  var body = document.getElementById("takers-body");
  var table = document.getElementById("takers-table");
  var empty = document.getElementById("no-takers");
  var awayNote = document.getElementById("away-note");
  var labels = { name: "", status: "", answered: "", away: "" };
  if (table) {
    var heads = table.querySelectorAll("thead th");
    labels.name = heads[0].textContent;
    labels.status = heads[1].textContent;
    labels.answered = heads[2].textContent;
    labels.away = heads[3] ? heads[3].textContent : "";
  }
  var of = body ? body.getAttribute("data-of") : "/";

  // --- "handed in" notes ------------------------------------------------------------------------
  // Attempts already finished when the page was drawn are never announced; every attempt that
  // finishes later is, once. Each note stays SHOW_MS; at most MAX_SHOWN are on screen, the rest wait.
  var SHOW_MS = 5000;
  var MAX_SHOWN = 3;
  var host = document.getElementById("toasts");
  var seen = {};
  var seeded = root.hasAttribute("data-finished");
  (root.getAttribute("data-finished") || "").split(",").forEach(function (id) {
    if (id) seen[id] = true;
  });
  var waiting = [];
  var shown = 0;

  function showNext() {
    if (!host) return;
    while (shown < MAX_SHOWN && waiting.length) {
      var t = waiting.shift();
      var note = document.createElement("div");
      note.className = "toast";
      var caption = document.createElement("span");
      caption.className = "toast-caption";
      caption.textContent =
        host.getAttribute(t.status === "auto_submitted" ? "data-caption-auto" : "data-caption") ||
        "";
      var name = document.createElement("span");
      name.className = "toast-name";
      name.textContent = t.name;
      note.appendChild(caption);
      note.appendChild(document.createTextNode(" "));
      note.appendChild(name);
      host.appendChild(note);
      shown++;
      setTimeout(remover(note), SHOW_MS);
    }
  }

  function remover(note) {
    return function () {
      note.classList.add("toast-out");
      // the fade-out is short; without animations (reduced motion) it is removed at once
      setTimeout(function () {
        if (note.parentNode) note.parentNode.removeChild(note);
        shown--;
        showNext();
      }, window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 250);
    };
  }

  function announce(takers) {
    takers.forEach(function (t) {
      if (t.status === "in_progress" || t.id === undefined) return;
      var key = String(t.id);
      if (seen[key]) return;
      seen[key] = true;
      if (seeded) waiting.push(t);
    });
    seeded = true; // without server data the first answer only fills `seen`
    showNext();
  }

  // --- takers table -----------------------------------------------------------------------------
  // Builds the same markup as templates/delivery/share.html (card pattern of base.css).
  function cell(label, cls) {
    var td = document.createElement("td");
    if (label) td.setAttribute("data-label", label);
    if (cls) td.className = cls;
    return td;
  }

  function awayCell(t) {
    var td = cell(labels.away, "away-cell" + (t.away_count ? "" : " away-none"));
    if (t.away_count) {
      var badge = document.createElement("span");
      badge.className = "away-badge";
      badge.title = t.away_text;
      var visible = document.createElement("span");
      visible.setAttribute("aria-hidden", "true");
      visible.textContent = "↗ " + t.away_short;
      var spoken = document.createElement("span");
      spoken.className = "visually-hidden";
      spoken.textContent = t.away_text;
      badge.appendChild(visible);
      badge.appendChild(spoken);
      td.appendChild(badge);
    } else {
      var dash = document.createElement("span");
      dash.className = "muted";
      dash.textContent = "–";
      td.appendChild(dash);
    }
    return td;
  }

  function render(data) {
    document.getElementById("c-joined").textContent = data.joined;
    document.getElementById("c-progress").textContent = data.in_progress;
    document.getElementById("c-submitted").textContent = data.submitted;
    announce(data.takers);
    if (!body) return;
    body.textContent = "";
    var anyAway = false;
    data.takers.forEach(function (t) {
      var tr = document.createElement("tr");
      var nameCell = cell("", "cell-title");
      var nameText = document.createElement("span");
      nameText.textContent = t.name;
      if (t.group) {
        var group = document.createElement("span");
        group.className = "muted";
        group.textContent = " (" + t.group + ")";
        nameText.appendChild(group);
      }
      if (t.variant) {
        var variant = document.createElement("span");
        variant.className = "muted";
        variant.textContent = " · " + t.variant;
        nameText.appendChild(variant);
      }
      nameCell.appendChild(nameText);
      tr.appendChild(nameCell);
      var statusCell = cell(labels.status);
      if (t.status !== "in_progress") {
        var done = document.createElement("span");
        done.className = "status-ok";
        done.textContent = t.status_label;
        statusCell.appendChild(done);
      } else {
        statusCell.textContent = t.status_label;
      }
      tr.appendChild(statusCell);
      var answeredCell = cell(labels.answered, "num");
      // variants may differ in length: every taker has their own total
      answeredCell.textContent = t.answered + " " + of + " " + (t.total || data.total_questions);
      tr.appendChild(answeredCell);
      if (labels.away) tr.appendChild(awayCell(t));
      if (t.away_count) anyAway = true;
      body.appendChild(tr);
    });
    table.hidden = data.takers.length === 0;
    if (empty) empty.hidden = data.takers.length !== 0;
    if (awayNote && anyAway) awayNote.hidden = false;
  }

  function poll() {
    fetch(url, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (data) render(data);
      })
      .catch(function () {});
  }

  setInterval(poll, pollMs);
})();
