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

  function cell(text, label, cls) {
    var td = document.createElement("td");
    td.setAttribute("data-label", label);
    if (cls) td.className = cls;
    td.textContent = text;
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
      tr.appendChild(cell(t.name, labels.name));
      tr.appendChild(cell(t.status_label, labels.status));
      tr.appendChild(
        cell(t.answered + " " + of + " " + data.total_questions, labels.answered, "num")
      );
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
