// Attempt sheet: the arrow keys step to the previous / next result of the session, in the order
// of the results table the teacher came from (the links carry its filter and sort). Not while
// typing, and not with a modifier key held. Points or comments typed but not saved yet are not
// lost silently: leaving through these links or keys asks first.
(function () {
  "use strict";
  var prev = document.getElementById("sheet-prev");
  var next = document.getElementById("sheet-next");
  if (!prev && !next) return;
  var steps = document.querySelector(".sheet-steps");
  var question = steps ? steps.getAttribute("data-unsaved") : "";
  var form = document.getElementById("review-form");
  var dirty = false;

  document.addEventListener("input", function (ev) {
    if (form && ev.target && ev.target.form === form) dirty = true;
  });
  if (form) {
    form.addEventListener("submit", function () {
      dirty = false;
    });
  }

  function mayLeave() {
    return !dirty || !question || window.confirm(question);
  }

  [prev, next].forEach(function (link) {
    if (!link) return;
    link.addEventListener("click", function (ev) {
      if (!mayLeave()) ev.preventDefault();
    });
  });

  function typing(target) {
    if (!target) return false;
    var tag = target.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.defaultPrevented || ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
    var link = ev.key === "ArrowLeft" ? prev : ev.key === "ArrowRight" ? next : null;
    if (!link || typing(ev.target)) return;
    ev.preventDefault();
    if (mayLeave()) window.location.href = link.href;
  });
})();
