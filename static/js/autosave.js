// Debounced autosave of changed answers, answered counter, save status line and choose_n cap.
// The form works without this file: submit posts every answer.
(function () {
  "use strict";
  var form = document.getElementById("take-form");
  if (!form || !window.fetch) return;
  var url = form.getAttribute("data-save-url");
  // Teacher preview: keep the counter and the choose_n cap, but never send anything.
  var preview = form.hasAttribute("data-preview");
  var token = form.querySelector("input[name=csrfmiddlewaretoken]");
  var counter = document.getElementById("answered-count");
  var pending = {};
  // Test page opened before an attempt exists: the first save also sends the taker details.
  var unstarted = form.hasAttribute("data-unstarted");
  var timer = null;
  var DELAY = 800;
  // Details the server refused (wrong PIN, no name picked...): do not send the same ones again
  // until the taker changes something, so a wrong PIN is not counted once per answer.
  var rejected = null;
  var note = document.getElementById("details-note");
  // Save status in the bottom bar: empty until the first save, then "Saved" or "No connection".
  var statusEl = document.getElementById("save-status");
  var everSaved = false;
  var DETAILS = 'input[name^="tf_"], input[name="access_code"], input[name="pin"], select[name="student"]';

  function questionId(name) {
    return name.indexOf("q_") === 0 ? name.slice(2) : null;
  }

  function currentValue(name, isChoice) {
    var fields = form.querySelectorAll('[name="' + name + '"]');
    if (isChoice) {
      var picked = [];
      fields.forEach(function (f) {
        if (f.checked) picked.push(f.value);
      });
      return picked;
    }
    return fields.length ? fields[0].value : "";
  }

  function updateCount() {
    if (!counter) return;
    var done = 0;
    form.querySelectorAll("fieldset.question").forEach(function (fs) {
      var inputs = fs.querySelectorAll("input, textarea");
      for (var i = 0; i < inputs.length; i++) {
        var f = inputs[i];
        var isBox = f.type === "radio" || f.type === "checkbox";
        if (isBox ? f.checked : f.value.trim() !== "") {
          done++;
          break;
        }
      }
    });
    counter.textContent = String(done);
  }

  function details() {
    var body = { unstarted: true };
    var t = form.querySelector("input[name=attempt_token]");
    if (t) body.attempt_token = t.value;
    form.querySelectorAll(DETAILS).forEach(function (f) {
      body[f.name] = f.value;
    });
    return body;
  }

  function isDetail(name) {
    return (
      name.indexOf("tf_") === 0 || name === "access_code" || name === "pin" || name === "student"
    );
  }

  function showNote(errors) {
    if (!note) return;
    note.textContent = errors && errors.length ? errors.join(" ") : "";
    note.hidden = !(errors && errors.length);
  }

  function setStatus(kind) {
    if (!statusEl) return;
    statusEl.textContent = statusEl.getAttribute("data-" + kind) || "";
    statusEl.classList.toggle("save-offline", kind === "offline");
  }

  function flush() {
    timer = null;
    if (preview) pending = {};
    if (preview || !Object.keys(pending).length) return;
    var extra = unstarted ? details() : {};
    var signature = JSON.stringify(extra);
    if (unstarted && signature === rejected) return; // wait until the details change
    var batch = pending;
    pending = {};
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": token ? token.value : "",
      },
      body: JSON.stringify(
        Object.assign({ answers: batch }, extra)
      ),
    })
      .then(function (r) {
        if (r.status === 409) {
          return r.json().then(function (d) {
            window.location.href = d.url;
          });
        }
        if (r.status >= 500) throw new Error("server error");
        return r.json().then(function (d) {
          if (d.started === false) {
            // Details (name, PIN, access code) not valid yet: keep answers, retry when they change.
            rejected = signature;
            showNote(d.errors);
            Object.keys(batch).forEach(function (k) {
              if (!(k in pending)) pending[k] = batch[k];
            });
          } else if (d.started) {
            unstarted = false;
            rejected = null;
            showNote(null);
            everSaved = true;
            setStatus("saved");
            if (d.left !== null && d.left !== undefined && window.ktStartTimer) {
              window.ktStartTimer(d.left);
            }
          }
        });
      })
      .catch(function () {
        // Network hiccup: keep the values and retry shortly.
        setStatus("offline");
        Object.keys(batch).forEach(function (k) {
          if (!(k in pending)) pending[k] = batch[k];
        });
        timer = setTimeout(flush, 5000);
      });
  }

  function onChange(ev) {
    var t = ev.target;
    var qid = t.name ? questionId(t.name) : null;
    if (!qid) {
      if (t.name && isDetail(t.name) && unstarted && Object.keys(pending).length) {
        if (timer) clearTimeout(timer);
        timer = setTimeout(flush, DELAY);
      }
      return;
    }
    if (t.type === "checkbox" && t.hasAttribute("data-max") && t.checked) {
      var max = parseInt(t.getAttribute("data-max"), 10);
      var count = form.querySelectorAll('[name="' + t.name + '"]:checked').length;
      if (count > max) {
        t.checked = false;
        return;
      }
    }
    var isChoice = t.type === "radio" || t.type === "checkbox";
    pending[qid] = currentValue(t.name, isChoice);
    updateCount();
    if (timer) clearTimeout(timer);
    timer = setTimeout(flush, DELAY);
  }

  form.addEventListener("change", onChange);
  form.addEventListener("input", function (ev) {
    if (ev.target.type === "text" || ev.target.tagName === "TEXTAREA") onChange(ev);
  });
  window.addEventListener("offline", function () {
    setStatus("offline");
  });
  window.addEventListener("online", function () {
    if (!Object.keys(pending).length && !timer && everSaved) setStatus("saved");
    else flush();
  });
})();
