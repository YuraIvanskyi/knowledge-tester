// Countdown display. The server deadline is authoritative; at 0 the form is submitted.
(function () {
  "use strict";
  var el = document.getElementById("timer");
  var form = document.getElementById("take-form");
  if (!el || !form) return;
  var end = null;
  var submitted = false;
  var ticking = false;

  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function tick() {
    if (end === null) return;
    var secs = Math.max(0, Math.round((end - Date.now()) / 1000));
    el.textContent = Math.floor(secs / 60) + ":" + pad(secs % 60);
    if (secs <= 0 && !submitted) {
      submitted = true;
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
