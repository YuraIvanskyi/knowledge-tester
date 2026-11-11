// Countdown display. The server deadline is authoritative; at 0 the form is submitted.
(function () {
  "use strict";
  var el = document.getElementById("timer");
  var form = document.getElementById("take-form");
  if (!el || !form) return;
  var left = parseInt(el.getAttribute("data-seconds-left"), 10);
  if (isNaN(left)) return;
  var end = Date.now() + left * 1000;
  var submitted = false;

  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function tick() {
    var secs = Math.max(0, Math.round((end - Date.now()) / 1000));
    el.textContent = Math.floor(secs / 60) + ":" + pad(secs % 60);
    if (secs <= 0 && !submitted) {
      submitted = true;
      form.submit();
    }
  }

  tick();
  setInterval(tick, 1000);
})();
