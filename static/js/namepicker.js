// Optional search box above the "pick your name" list. The list is a plain <select> and works
// without this file; this only narrows long lists while the student types.
(function () {
  "use strict";
  var select = document.querySelector("select[data-namepicker]");
  if (!select || !select.options || select.options.length < 9) return;

  var items = Array.prototype.slice.call(select.options).map(function (o) {
    return { value: o.value, text: o.text, disabled: o.disabled };
  });
  var placeholder = items[0]; // "Choose your name"
  var names = items.slice(1);

  function norm(text) {
    return text
      .toLowerCase()
      .replace(/[’ʼʹ‘`´′]/g, "'")
      .replace(/\s+/g, " ")
      .trim();
  }

  var id = "student-filter";
  var label = document.createElement("label");
  label.className = "visually-hidden";
  label.setAttribute("for", id);
  label.textContent = select.getAttribute("data-filter-label") || "";
  var box = document.createElement("input");
  box.type = "search";
  box.id = id;
  box.autocomplete = "off";
  box.spellcheck = false;
  box.className = "name-filter";
  box.placeholder = select.getAttribute("data-filter-placeholder") || "";
  box.setAttribute("aria-controls", select.id);
  select.parentNode.insertBefore(label, select);
  select.parentNode.insertBefore(box, select);

  function addOption(item, selected) {
    var option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.text;
    option.disabled = item.disabled;
    option.selected = selected;
    select.appendChild(option);
  }

  function filter() {
    var words = norm(box.value).split(" ").filter(Boolean);
    var keep = select.value;
    var hits = names.filter(function (item) {
      var text = norm(item.text);
      return words.every(function (w) {
        return text.indexOf(w) !== -1;
      });
    });
    while (select.firstChild) select.removeChild(select.firstChild);
    addOption(placeholder, false);
    hits.forEach(function (item) {
      addOption(item, item.value === keep);
    });
    // One match left: pick it, so the student only has to check and go on.
    var pickable = hits.filter(function (item) {
      return !item.disabled;
    });
    if (words.length && pickable.length === 1 && select.value !== pickable[0].value) {
      select.value = pickable[0].value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  box.addEventListener("input", filter);
  // Enter in the search box must not submit the whole test.
  box.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") ev.preventDefault();
  });
})();
