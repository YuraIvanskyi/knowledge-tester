// "Copy" buttons: <button data-copy="id of a textarea" data-done="..." data-failed="...">.
// The app is served over plain HTTP on the LAN, where the Clipboard API does not exist, so the
// old select-and-copy command comes first. Without this file the text can still be selected.
(function () {
  "use strict";
  var timers = new WeakMap();

  function say(button, text) {
    var status = button.parentNode ? button.parentNode.querySelector(".copy-status") : null;
    if (!status) return;
    status.textContent = text || "";
    clearTimeout(timers.get(status));
    timers.set(
      status,
      setTimeout(function () {
        status.textContent = "";
      }, 4000)
    );
  }

  function copy(button) {
    var box = document.getElementById(button.getAttribute("data-copy"));
    if (!box) return;
    box.focus();
    box.select();
    box.setSelectionRange(0, box.value.length); // iOS
    var done = false;
    try {
      done = document.execCommand("copy");
    } catch (e) {
      done = false;
    }
    if (done) {
      say(button, button.getAttribute("data-done"));
      return;
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(box.value).then(
        function () {
          say(button, button.getAttribute("data-done"));
        },
        function () {
          say(button, button.getAttribute("data-failed"));
        }
      );
      return;
    }
    // The text stays selected, so Ctrl+C or the phone's own "Copy" finishes the job.
    say(button, button.getAttribute("data-failed"));
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("[data-copy]") : null;
    if (button) copy(button);
  });
})();
