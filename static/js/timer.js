// Countdown display. The server deadline is authoritative; at 0 the form is submitted.
// The teacher can add time or close the session, so the page asks the server now and then
// (and once more right before the automatic submit) how much time is really left.
(function () {
  "use strict";
  var el = document.getElementById("timer");
  var form = document.getElementById("take-form");
  if (!el || !form) return;
  var end = null;
  var submitted = false;
  var ticking = false;
  var warned = false;
  var WARN_AT = 60; // seconds left when the warning state starts
  var NOTE_MS = 8000; // how long the visible note next to the bar stays
  var SYNC_MS = 30000; // how often the server is asked for the time left
  var SYNC_WAIT_MS = 4000; // at 0: how long to wait for the server before submitting anyway
  var DRIFT_MS = 3000; // smaller differences are network delay, not a changed deadline
  var box = el.closest ? el.closest(".timer") : null;
  var live = document.getElementById("timer-live");
  var note = document.getElementById("timer-note");
  // Absent in the teacher's preview: nothing is asked there.
  var saveUrl = form.getAttribute("data-save-url");
  var token = form.querySelector("input[name=csrfmiddlewaretoken]");

  // One minute left: bold red timer, a screen-reader announcement and a short visible note.
  function warn() {
    warned = true;
    var text = box ? box.getAttribute("data-warn") : "";
    if (box) box.classList.add("timer-warn");
    if (!text) return;
    if (live) live.textContent = text;
    if (note) {
      note.textContent = text;
      note.hidden = false;
      setTimeout(function () {
        note.hidden = true;
      }, NOTE_MS);
    }
  }

  // Time was added: back to the calm state, so the warning can fire again later.
  function unwarn() {
    warned = false;
    if (box) box.classList.remove("timer-warn");
    if (live) live.textContent = "";
    if (note) note.hidden = true;
  }

  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function autoSubmit() {
    // Time is up: finish without the "unanswered questions" question.
    var flag = document.createElement("input");
    flag.type = "hidden";
    flag.name = "confirm_unanswered";
    flag.value = "1";
    form.appendChild(flag);
    form.submit();
  }

  // Ask the server for the time left (an autosave without answers). `atZero` is the check
  // right before the automatic submit: any failure there submits, as the page always did.
  function sync(atZero) {
    var decided = false;
    function finish(left) {
      if (!atZero || decided) return;
      decided = true;
      if (typeof left === "number" && left > 2) {
        submitted = false; // the deadline moved; keep counting
      } else {
        autoSubmit();
      }
    }
    if (!saveUrl || !window.fetch) {
      finish(null);
      return;
    }
    if (atZero) setTimeout(finish, SYNC_WAIT_MS);
    fetch(saveUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": token ? token.value : "",
      },
      body: JSON.stringify({ answers: {} }),
    })
      .then(function (r) {
        if (r.status === 409) {
          // Finished on the server (time ran out, or the teacher closed the session).
          return r.json().then(function (d) {
            decided = true;
            window.location.href = d.url;
          });
        }
        if (!r.ok) throw new Error("not available");
        return r.json().then(function (d) {
          if (typeof d.left === "number") window.ktStartTimer(d.left);
          finish(d.left);
        });
      })
      .catch(function () {
        finish(null);
      });
  }

  function tick() {
    if (end === null) return;
    var secs = Math.max(0, Math.round((end - Date.now()) / 1000));
    el.textContent = Math.floor(secs / 60) + ":" + pad(secs % 60);
    if (secs <= WARN_AT && !warned) warn();
    if (secs <= 0 && !submitted) {
      submitted = true;
      sync(true);
    }
  }

  // The attempt may start after page load (first autosave); autosave.js then calls this.
  // Called again with every answer from the server: a clearly different value means the
  // teacher changed the deadline, and the countdown follows it.
  window.ktStartTimer = function (seconds) {
    if (typeof seconds !== "number") return;
    var fresh = Date.now() + seconds * 1000;
    if (ticking) {
      if (Math.abs(fresh - end) > DRIFT_MS) {
        end = fresh;
        if (seconds > WARN_AT) unwarn();
        tick();
      }
      return;
    }
    end = fresh;
    ticking = true;
    tick();
    setInterval(tick, 1000);
    setInterval(function () {
      if (!document.hidden && !submitted) sync(false);
    }, SYNC_MS);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && !submitted) sync(false);
    });
  };

  var left = parseInt(el.getAttribute("data-seconds-left"), 10);
  if (!isNaN(left)) window.ktStartTimer(left);
})();
