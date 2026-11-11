// Debounced autosave of changed answers, answered counter, and choose_n selection cap.
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
    form.querySelectorAll('input[name^="tf_"], input[name="access_code"]').forEach(function (f) {
      body[f.name] = f.value;
    });
    return body;
  }

  function flush() {
    timer = null;
    var batch = pending;
    pending = {};
    if (preview || !Object.keys(batch).length) return;
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": token ? token.value : "",
      },
      body: JSON.stringify(
        Object.assign({ answers: batch }, unstarted ? details() : {})
      ),
    })
      .then(function (r) {
        if (r.status === 409) {
          return r.json().then(function (d) {
            window.location.href = d.url;
          });
        }
        return r.json().then(function (d) {
          if (d.started === false) {
            // Details (name, access code) not valid yet: keep answers, retry when they change.
            Object.keys(batch).forEach(function (k) {
              if (!(k in pending)) pending[k] = batch[k];
            });
          } else if (d.started) {
            unstarted = false;
            if (d.left !== null && d.left !== undefined && window.ktStartTimer) {
              window.ktStartTimer(d.left);
            }
          }
        });
      })
      .catch(function () {
        // Network hiccup: keep the values and retry shortly.
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
      var isDetail = t.name && (t.name.indexOf("tf_") === 0 || t.name === "access_code");
      if (isDetail && unstarted && Object.keys(pending).length) {
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
  window.addEventListener("online", flush);
})();
