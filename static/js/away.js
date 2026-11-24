// Leaving the test page (another tab or app, or another window on a computer) is reported to
// the server, which shows it to the teacher. A departure is sent at once (so the teacher sees it
// while the student is away), the time away when the student is back. Unsent reports are kept
// and sent again on the next return, and when the attempt starts (event "kt:started" from
// autosave.js). Not loaded in the teacher's preview.
(function () {
  "use strict";
  var form = document.getElementById("take-form");
  if (!form || !window.fetch || form.hasAttribute("data-preview")) return;
  var url = form.getAttribute("data-away-url");
  if (!url) return;
  var csrf = form.querySelector("input[name=csrfmiddlewaretoken]");
  var pageToken = form.querySelector("input[name=attempt_token]");
  var BLUR_MS = 1000; // a window that only loses focus counts after this long (no flicker)

  var since = null; // when the student left, or null while on the page
  var counted = false; // this departure was counted already
  var blurTimer = null;
  var queue = { count: 0, seconds: 0 };
  var sending = false;

  function away() {
    return document.hidden || (document.hasFocus ? !document.hasFocus() : false);
  }

  function send() {
    if (sending || (!queue.count && !queue.seconds)) return;
    var batch = queue;
    queue = { count: 0, seconds: 0 };
    sending = true;
    var body = { count: batch.count, seconds: batch.seconds };
    if (pageToken) body.attempt_token = pageToken.value;
    function keep() {
      queue.count += batch.count;
      queue.seconds += batch.seconds;
    }
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf ? csrf.value : "" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        return r.ok ? r.json() : { recorded: false };
      })
      .then(function (d) {
        sending = false;
        if (!d || !d.recorded) keep(); // no attempt yet: send again once it exists
        else send(); // anything that came in while this one was on its way
      })
      .catch(function () {
        sending = false;
        keep();
      });
  }

  function countDeparture() {
    if (since === null || counted) return;
    counted = true;
    queue.count += 1;
    send();
  }

  function leave(hidden) {
    if (since === null) {
      since = Date.now();
      counted = false;
    }
    if (hidden) {
      countDeparture(); // the page may never get to run a timer again: count now
    } else if (!counted && !blurTimer) {
      blurTimer = setTimeout(function () {
        blurTimer = null;
        if (away()) countDeparture();
      }, BLUR_MS);
    }
  }

  function back() {
    if (blurTimer) {
      clearTimeout(blurTimer);
      blurTimer = null;
    }
    if (since === null) return;
    var seconds = Math.round((Date.now() - since) / 1000);
    var wasCounted = counted;
    since = null;
    counted = false;
    if (!wasCounted) return; // a blink shorter than BLUR_MS
    queue.seconds += seconds;
    send();
  }

  function check() {
    if (away()) leave(document.hidden);
    else back();
  }

  document.addEventListener("visibilitychange", check);
  window.addEventListener("blur", check);
  window.addEventListener("focus", check);
  window.addEventListener("pagehide", function () {
    if (since !== null) countDeparture();
  });
  document.addEventListener("kt:started", send);
})();
