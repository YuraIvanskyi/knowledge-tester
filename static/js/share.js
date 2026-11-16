// Live counters and takers table for the teacher share screen (polls every 5 s).
(function () {
  "use strict";
  var root = document.getElementById("share");
  if (!root || !window.fetch) return;
  var url = root.getAttribute("data-stats-url");
  var body = document.getElementById("takers-body");
  var table = document.getElementById("takers-table");
  var empty = document.getElementById("no-takers");
  var labels = { name: "", status: "", answered: "" };
  if (table) {
    var heads = table.querySelectorAll("thead th");
    labels.name = heads[0].textContent;
    labels.status = heads[1].textContent;
    labels.answered = heads[2].textContent;
  }
  var of = body ? body.getAttribute("data-of") : "/";

  // Builds the same markup as templates/delivery/share.html (card pattern of base.css).
  function cell(label, cls) {
    var td = document.createElement("td");
    if (label) td.setAttribute("data-label", label);
    if (cls) td.className = cls;
    return td;
  }

  function render(data) {
    document.getElementById("c-joined").textContent = data.joined;
    document.getElementById("c-progress").textContent = data.in_progress;
    document.getElementById("c-submitted").textContent = data.submitted;
    if (!body) return;
    body.textContent = "";
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
      body.appendChild(tr);
    });
    table.hidden = data.takers.length === 0;
    if (empty) empty.hidden = data.takers.length !== 0;
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

  setInterval(poll, 5000);
})();
