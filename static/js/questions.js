// Question navigator, "one question per page" and the check before submitting with questions
// left empty. The page works without this file: every question shows, the navigator is plain
// links, and the server asks before submitting unanswered questions (the same panels).
(function () {
  "use strict";
  var form = document.getElementById("take-form");
  if (!form || !form.querySelectorAll) return;
  var fieldsets = Array.prototype.slice.call(form.querySelectorAll("fieldset.question"));
  if (!fieldsets.length) return;

  var nav = document.getElementById("qnav");
  var answeredWord = nav ? nav.getAttribute("data-answered") || "" : "";
  var pager = document.getElementById("pager");
  var submitArea = document.getElementById("submit-area");
  var serverPanels = ["missing", "unanswered"]
    .map(function (id) {
      return document.getElementById(id);
    })
    .filter(Boolean);
  var missingPanel = document.getElementById("missing-js");
  var emptyPanel = document.getElementById("unanswered-js");
  var countLine = emptyPanel ? emptyPanel.querySelector("[data-count]") : null;
  var countTemplate = countLine ? countLine.textContent : "";
  var submitMain = document.getElementById("submit-main");
  var paging = form.hasAttribute("data-one-per-page") && fieldsets.length > 1 && !!pager;
  var current = 0;

  function qid(fs) {
    return fs.getAttribute("data-qid");
  }

  function indexOf(id) {
    for (var i = 0; i < fieldsets.length; i++) if (qid(fieldsets[i]) === id) return i;
    return -1;
  }

  // Same rule as the counter in autosave.js: a ticked box or a non-blank text.
  function isAnswered(fs) {
    var inputs = fs.querySelectorAll("input, textarea");
    for (var i = 0; i < inputs.length; i++) {
      var f = inputs[i];
      var isBox = f.type === "radio" || f.type === "checkbox";
      if (isBox ? f.checked : f.value.trim() !== "") return true;
    }
    return false;
  }

  // Every navigator button of one question (top row and the panels) shows its state.
  function refreshButtons() {
    fieldsets.forEach(function (fs, i) {
      var done = isAnswered(fs);
      var buttons = form.querySelectorAll('.qnav-btn[data-qid="' + qid(fs) + '"]');
      Array.prototype.forEach.call(buttons, function (a) {
        a.classList.toggle("is-done", done);
        if (done) a.classList.remove("is-missing");
        var label = a.getAttribute("data-label") || "";
        a.setAttribute("aria-label", done && answeredWord ? label + ", " + answeredWord : label);
        if (paging && nav && nav.contains(a)) {
          if (i === current) a.setAttribute("aria-current", "step");
          else a.removeAttribute("aria-current");
        }
      });
    });
  }

  // --- one question per page -----------------------------------------------------------------

  var prev = pager ? pager.querySelector(".pager-prev") : null;
  var next = pager ? pager.querySelector(".pager-next") : null;

  function bringIntoView(el) {
    var top = el.getBoundingClientRect().top;
    if (top < 0 || top > window.innerHeight * 0.5) {
      el.scrollIntoView({ block: "start" });
    }
  }

  function showPage(index, focus) {
    current = Math.max(0, Math.min(index, fieldsets.length - 1));
    var last = current === fieldsets.length - 1;
    fieldsets.forEach(function (fs, i) {
      fs.hidden = i !== current;
    });
    if (prev) prev.hidden = current === 0;
    if (next) next.hidden = last;
    if (submitArea) submitArea.hidden = !last;
    refreshButtons();
    if (focus) {
      bringIntoView(nav && !nav.hidden ? nav : fieldsets[current]);
      var legend = fieldsets[current].querySelector("legend");
      if (legend) legend.focus({ preventScroll: true });
    }
  }

  function goTo(id) {
    var i = indexOf(id);
    if (i < 0) return false;
    if (paging) {
      showPage(i, true);
    } else {
      fieldsets[i].scrollIntoView({ block: "start" });
      var legend = fieldsets[i].querySelector("legend");
      if (legend) legend.focus({ preventScroll: true });
    }
    return true;
  }

  // Navigator buttons and the links in the panels: open the question (its page when paging).
  form.addEventListener("click", function (ev) {
    var a = ev.target.closest ? ev.target.closest('a[href^="#q-"]') : null;
    if (a && goTo(a.getAttribute("href").slice(3))) ev.preventDefault();
  });

  if (paging) {
    pager.hidden = false;
    form.classList.add("is-paged");
    pager.addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("button[data-step]") : null;
      if (b) showPage(current + parseInt(b.getAttribute("data-step"), 10), true);
    });
    var hash = window.location.hash;
    var wanted = hash.indexOf("#q-") === 0 ? indexOf(hash.slice(3)) : -1;
    showPage(Math.max(0, wanted), false);
  }

  // --- asking before submitting with empty questions -----------------------------------------

  function buttonFor(fs, missing) {
    var source = nav ? nav.querySelector('.qnav-btn[data-qid="' + qid(fs) + '"]') : null;
    var a = source ? source.cloneNode(true) : document.createElement("a");
    a.removeAttribute("aria-current");
    a.classList.remove("is-done");
    a.classList.toggle("is-missing", !!missing);
    return a;
  }

  function fill(panel, list, missing) {
    var box = panel.querySelector("[data-list]");
    box.textContent = "";
    list.forEach(function (fs) {
      box.appendChild(buttonFor(fs, missing));
    });
  }

  function emptyOnes() {
    var empty = [];
    var missing = [];
    fieldsets.forEach(function (fs) {
      if (isAnswered(fs)) return;
      empty.push(fs);
      if (fs.hasAttribute("data-required")) missing.push(fs);
    });
    return { empty: empty, missing: missing };
  }

  // Shows the right panel for the current answers; returns it, or null when nothing is empty.
  // While "Submit anyway" is offered, the plain Submit button steps aside.
  function ask() {
    var state = emptyOnes();
    if (missingPanel) missingPanel.hidden = !state.missing.length;
    if (emptyPanel) emptyPanel.hidden = !!state.missing.length || !state.empty.length;
    if (submitMain) {
      submitMain.hidden = !!emptyPanel && !emptyPanel.hidden;
      submitMain.classList.add("btn-primary"); // the server makes it plain next to its panel
    }
    if (state.missing.length && missingPanel) {
      fill(missingPanel, state.missing, true);
      return missingPanel;
    }
    if (state.empty.length && emptyPanel) {
      fill(emptyPanel, state.empty, false);
      if (countLine) {
        countLine.textContent = countTemplate.replace(
          "__DONE__",
          String(fieldsets.length - state.empty.length)
        );
      }
      return emptyPanel;
    }
    return null;
  }

  function asking() {
    return (missingPanel && !missingPanel.hidden) || (emptyPanel && !emptyPanel.hidden);
  }

  function present(panel) {
    if (paging) showPage(fieldsets.length - 1, false); // the panels sit on the last page
    panel.scrollIntoView({ block: "center" });
    panel.focus({ preventScroll: true });
  }

  form.addEventListener("submit", function (ev) {
    var by = ev.submitter;
    // The "Submit anyway" button, or a browser that does not say: the server decides.
    if (!by || by.name === "confirm_unanswered") return;
    var panel = ask();
    if (!panel) return;
    ev.preventDefault();
    present(panel);
  });

  // The server asked already (the page came back from Submit): the same panel, kept live here.
  if (serverPanels.length) {
    serverPanels.forEach(function (p) {
      p.hidden = true;
    });
    var asked = ask();
    if (asked) present(asked);
  }

  function onAnswer() {
    refreshButtons();
    if (asking()) ask(); // keep the open panel up to date while the student answers from it
  }

  form.addEventListener("change", onAnswer);
  form.addEventListener("input", function (ev) {
    if (ev.target.type === "text" || ev.target.tagName === "TEXTAREA") onAnswer();
  });
  refreshButtons();
})();
