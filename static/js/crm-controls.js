/* ============================================================
   CRM Controls — custom date picker, select, search clear
   Lightweight vanilla JS, no dependencies.
   ============================================================ */
(function () {
  "use strict";

  var DOW_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
  var MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
  ];

  /* ── helpers ─────────────────────────────────────────── */
  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function $$(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }
  function on(el, evt, fn) { if (el) el.addEventListener(evt, fn); }
  function off(el, evt, fn) { if (el) el.removeEventListener(evt, fn); }
  function create(tag, cls, attrs) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (attrs) Object.keys(attrs).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    return el;
  }
  function formatDate(d) {
    var y = d.getFullYear();
    var m = ("0" + (d.getMonth() + 1)).slice(-2);
    var day = ("0" + d.getDate()).slice(-2);
    return y + "-" + m + "-" + day;
  }
  function parseDate(s) {
    if (!s) return null;
    var parts = s.split("-");
    if (parts.length !== 3) return null;
    return new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
  }
  function sameDay(a, b) {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  /* ── SEARCH CLEAR ────────────────────────────────────── */
  function initSearchClear() {
    $$(".toolbar__search").forEach(function (wrap) {
      var input = $("input", wrap);
      if (!input) return;
      var btn = create("button", "search-clear", { type: "button", "aria-label": "Очистить поиск" });
      btn.innerHTML = "&times;";
      wrap.appendChild(btn);
      function toggle() {
        wrap.classList.toggle("has-value", input.value.length > 0);
      }
      on(input, "input", toggle);
      on(btn, "click", function () {
        input.value = "";
        toggle();
        input.focus();
      });
      toggle();
    });
  }

  /* ── CUSTOM DATE PICKER ──────────────────────────────── */
  function initDatePickers() {
    $$(".crm-datetime-wrap").forEach(function (wrap) {
      var input = $("input.crm-datetime-input", wrap);
      var hiddenInput = $("input[type='hidden']", wrap);
      var mode = wrap.getAttribute("data-crm-mode") || "date"; // date | time | datetime
      var pickerEl = $("." + (mode === "time" ? "crm-time-grid" : "crm-datetime-picker"), wrap);
      if (!input) return;

      var currentDate = parseDate(input.value) || new Date();
      var currentMonth = new Date(currentDate.getFullYear(), currentDate.getMonth(), 1);

      function open() {
        closeAllPickers();
        if (pickerEl) {
          pickerEl.classList.add("is-open");
          if (mode !== "time") renderCalendar();
        }
      }

      function close() {
        if (pickerEl) pickerEl.classList.remove("is-open");
      }

      function renderCalendar() {
        if (!pickerEl) return;
        pickerEl.innerHTML = "";

        // Mode toggle for datetime
        if (mode === "datetime") {
          var toggleDiv = create("div", "crm-dp__mode-toggle");
          var dateBtn = create("button", "crm-dp__mode-btn is-active", { type: "button" });
          dateBtn.textContent = "Дата";
          var timeBtn = create("button", "crm-dp__mode-btn", { type: "button" });
          timeBtn.textContent = "Время";
          toggleDiv.appendChild(dateBtn);
          toggleDiv.appendChild(timeBtn);
          pickerEl.appendChild(toggleDiv);
          on(dateBtn, "click", function (e) {
            e.stopPropagation();
            dateBtn.classList.add("is-active");
            timeBtn.classList.remove("is-active");
            renderCalendar();
          });
          on(timeBtn, "click", function (e) {
            e.stopPropagation();
            timeBtn.classList.add("is-active");
            dateBtn.classList.remove("is-active");
            renderTimePicker();
          });
        }

        // Header
        var header = create("div", "crm-dp__header");
        var prevBtn = create("button", "crm-dp__nav", { type: "button", "aria-label": "Предыдущий месяц" });
        prevBtn.innerHTML = "&#8249;";
        var title = create("span", "crm-dp__title");
        title.textContent = MONTHS_RU[currentMonth.getMonth()] + " " + currentMonth.getFullYear();
        var nextBtn = create("button", "crm-dp__nav", { type: "button", "aria-label": "Следующий месяц" });
        nextBtn.innerHTML = "&#8250;";
        header.appendChild(prevBtn);
        header.appendChild(title);
        header.appendChild(nextBtn);
        pickerEl.appendChild(header);

        on(prevBtn, "click", function (e) {
          e.stopPropagation();
          currentMonth.setMonth(currentMonth.getMonth() - 1);
          renderCalendar();
        });
        on(nextBtn, "click", function (e) {
          e.stopPropagation();
          currentMonth.setMonth(currentMonth.getMonth() + 1);
          renderCalendar();
        });

        // Grid
        var grid = create("div", "crm-dp__grid");
        DOW_RU.forEach(function (d) {
          var dow = create("div", "crm-dp__dow");
          dow.textContent = d;
          grid.appendChild(dow);
        });

        var firstDay = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), 1);
        var startDay = (firstDay.getDay() + 6) % 7; // Monday=0
        var daysInMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 0).getDate();
        var today = new Date();

        // Previous month days
        var prevMonthDays = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), 0).getDate();
        for (var i = startDay - 1; i >= 0; i--) {
          var dayEl = create("button", "crm-dp__day is-other-month", { type: "button" });
          dayEl.textContent = prevMonthDays - i;
          grid.appendChild(dayEl);
        }

        // Current month days
        for (var d = 1; d <= daysInMonth; d++) {
          var thisDate = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), d);
          var dayEl = create("button", "crm-dp__day", { type: "button", tabindex: "0" });
          dayEl.textContent = d;
          if (sameDay(thisDate, today)) dayEl.classList.add("is-today");
          if (input.value && sameDay(thisDate, parseDate(input.value))) dayEl.classList.add("is-selected");
          (function (date) {
            on(dayEl, "click", function (e) {
              e.stopPropagation();
              selectDate(date);
            });
          })(thisDate);
          grid.appendChild(dayEl);
        }

        // Next month padding
        var totalCells = startDay + daysInMonth;
        var remaining = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7);
        for (var n = 1; n <= remaining; n++) {
          var dayEl = create("button", "crm-dp__day is-other-month", { type: "button" });
          dayEl.textContent = n;
          grid.appendChild(dayEl);
        }

        pickerEl.appendChild(grid);

        // Footer with "Today" button
        var footer = create("div", "crm-dp__footer");
        var todayBtn = create("button", "btn btn--ghost", { type: "button" });
        todayBtn.textContent = "Сегодня";
        var clearBtn = create("button", "btn btn--ghost", { type: "button" });
        clearBtn.textContent = "Очистить";
        footer.appendChild(todayBtn);
        footer.appendChild(clearBtn);
        pickerEl.appendChild(footer);

        on(todayBtn, "click", function (e) {
          e.stopPropagation();
          selectDate(new Date());
        });
        on(clearBtn, "click", function (e) {
          e.stopPropagation();
          input.value = "";
          if (hiddenInput) hiddenInput.value = "";
          close();
          input.dispatchEvent(new Event("change", { bubbles: true }));
        });
      }

      function renderTimePicker() {
        if (!pickerEl) return;
        pickerEl.innerHTML = "";

        var grid = create("div", "crm-time-grid");
        var currentTime = input.value || "";

        for (var h = 0; h < 24; h++) {
          for (var m = 0; m < 60; m += 15) {
            var timeStr = ("0" + h).slice(-2) + ":" + ("0" + m).slice(-2);
            var item = create("button", "crm-time-grid__item", { type: "button" });
            item.textContent = timeStr;
            if (currentTime === timeStr) item.classList.add("is-selected");
            (function (t) {
              on(item, "click", function (e) {
                e.stopPropagation();
                input.value = t;
                if (hiddenInput) hiddenInput.value = t;
                close();
                input.dispatchEvent(new Event("change", { bubbles: true }));
              });
            })(timeStr);
            grid.appendChild(item);
          }
        }
        pickerEl.appendChild(grid);
      }

      function selectDate(d) {
        var val = formatDate(d);
        input.value = val;
        if (hiddenInput) hiddenInput.value = val;
        currentDate = d;
        currentMonth = new Date(d.getFullYear(), d.getMonth(), 1);
        close();
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }

      on(input, "click", function (e) {
        e.stopPropagation();
        if (pickerEl && pickerEl.classList.contains("is-open")) {
          close();
        } else {
          open();
        }
      });

      on(input, "focus", function () {
        open();
      });

      // Store close function
      wrap._crmClose = close;
    });
  }

  function closeAllPickers() {
    $$(".crm-datetime-picker.is-open, .crm-time-grid.is-open, .crm-dropdown.is-open").forEach(function (el) {
      el.classList.remove("is-open");
    });
    $$(".crm-datetime-wrap").forEach(function (w) {
      if (w._crmClose) w._crmClose();
    });
  }

  /* ── CUSTOM SELECT ───────────────────────────────────── */
  function initCustomSelects() {
    $$("select.crm-select").forEach(function (sel) {
      // Wrap in container
      var wrap = create("div", "crm-select-wrap");
      sel.parentNode.insertBefore(wrap, sel);
      wrap.appendChild(sel);
      sel.style.display = "none";

      // Create custom trigger
      var trigger = create("div", "crm-select", {
        role: "combobox",
        tabindex: "0",
        "aria-expanded": "false",
        "aria-haspopup": "listbox"
      });
      wrap.insertBefore(trigger, sel);

      // Create dropdown
      var dropdown = create("div", "crm-dropdown", { role: "listbox" });
      wrap.appendChild(dropdown);

      function getSelectedText() {
        var opt = sel.options[sel.selectedIndex];
        return opt ? opt.textContent : "";
      }

      function render() {
        trigger.textContent = getSelectedText();
        dropdown.innerHTML = "";
        for (var i = 0; i < sel.options.length; i++) {
          var opt = sel.options[i];
          var item = create("div", "crm-dropdown__item", {
            role: "option",
            "data-value": opt.value
          });
          item.textContent = opt.textContent;
          if (i === sel.selectedIndex) {
            item.classList.add("is-selected");
            item.setAttribute("aria-selected", "true");
          }
          if (!opt.value && opt.textContent) {
            // placeholder/empty option
          }
          (function (idx) {
            on(item, "click", function (e) {
              e.stopPropagation();
              sel.selectedIndex = idx;
              trigger.textContent = getSelectedText();
              close();
              sel.dispatchEvent(new Event("change", { bubbles: true }));
            });
          })(i);
          dropdown.appendChild(item);
        }
      }

      function open() {
        closeAllPickers();
        render();
        dropdown.classList.add("is-open");
        trigger.setAttribute("aria-expanded", "true");
      }

      function close() {
        dropdown.classList.remove("is-open");
        trigger.setAttribute("aria-expanded", "false");
      }

      on(trigger, "click", function (e) {
        e.stopPropagation();
        if (dropdown.classList.contains("is-open")) {
          close();
        } else {
          open();
        }
      });

      on(trigger, "keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          if (dropdown.classList.contains("is-open")) close(); else open();
        } else if (e.key === "Escape") {
          close();
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          open();
          var first = $(".crm-dropdown__item", dropdown);
          if (first) first.focus();
        }
      });

      on(dropdown, "keydown", function (e) {
        var items = $$(".crm-dropdown__item", dropdown);
        var current = document.activeElement;
        var idx = items.indexOf(current);
        if (e.key === "Escape") {
          close();
          trigger.focus();
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          if (idx < items.length - 1) items[idx + 1].focus();
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          if (idx > 0) items[idx - 1].focus();
          else trigger.focus();
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (current && current.dataset.value !== undefined) {
            current.click();
          }
        }
      });

      // Sync when form resets
      var form = sel.closest("form");
      if (form) {
        on(form, "reset", function () {
          setTimeout(function () { render(); }, 10);
        });
      }

      render();
    });
  }

  /* ── SIDEBAR keyboard close on Escape ────────────────── */
  function initSidebarKeyboard() {
    var sidebar = document.getElementById("sidebar");
    var backdrop = document.getElementById("sidebar-backdrop");
    if (!sidebar || !backdrop) return;

    on(document, "keydown", function (e) {
      if (e.key === "Escape" && document.body.classList.contains("sidebar-open")) {
        document.body.classList.remove("sidebar-open");
        backdrop.hidden = true;
        var toggle = document.getElementById("sidebar-toggle");
        if (toggle) toggle.focus();
      }
    });

    // Focus trap in sidebar when open
    on(sidebar, "keydown", function (e) {
      if (e.key !== "Tab") return;
      if (!document.body.classList.contains("sidebar-open")) return;
      var focusable = $$("a, button, [tabindex]", sidebar);
      if (focusable.length === 0) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });
  }

  /* ── CLOSE ALL ON OUTSIDE CLICK ──────────────────────── */
  function initOutsideClick() {
    on(document, "click", function (e) {
      // Close pickers
      if (!e.target.closest(".crm-datetime-wrap")) {
        closeAllPickers();
      }
      if (!e.target.closest(".crm-select-wrap")) {
        $$(".crm-dropdown.is-open").forEach(function (d) {
          d.classList.remove("is-open");
        });
      }
    });
  }

  function initConfirmations() {
    $$('[data-confirm]').forEach(function (control) {
      on(control, "click", function (event) {
        if (!window.confirm(control.getAttribute("data-confirm"))) event.preventDefault();
      });
    });
  }

  /* ── INIT ────────────────────────────────────────────── */
  function init() {
    initSearchClear();
    initDatePickers();
    initCustomSelects();
    initSidebarKeyboard();
    initOutsideClick();
    initConfirmations();
  }

  if (document.readyState === "loading") {
    on(document, "DOMContentLoaded", init);
  } else {
    init();
  }
})();
