// Countdown display. The server deadline is authoritative; at 0 the form is submitted.
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
  var box = el.closest ? el.closest(".timer") : null;
  var live = document.getElementById("timer-live");
  var note = document.getElementById("timer-note");

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

  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function tick() {
    if (end === null) return;
    var secs = Math.max(0, Math.round((end - Date.now()) / 1000));
    el.textContent = Math.floor(secs / 60) + ":" + pad(secs % 60);
    if (secs <= WARN_AT && !warned) warn();
    if (secs <= 0 && !submitted) {
      submitted = true;
      // Time is up: finish without the "unanswered questions" question.
      var flag = document.createElement("input");
      flag.type = "hidden";
      flag.name = "confirm_unanswered";
      flag.value = "1";
      form.appendChild(flag);
      form.submit();
    }
  }

  // The attempt may start after page load (first autosave); autosave.js then calls this.
  window.ktStartTimer = function (seconds) {
    if (typeof seconds !== "number" || ticking) return;
    end = Date.now() + seconds * 1000;
    ticking = true;
    tick();
    setInterval(tick, 1000);
  };

  var left = parseInt(el.getAttribute("data-seconds-left"), 10);
  if (!isNaN(left)) window.ktStartTimer(left);
})();
