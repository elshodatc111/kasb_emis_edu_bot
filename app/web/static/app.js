(function () {
  "use strict";

  // ---- kun / tun rejimi ----
  function currentMode() {
    try { var t = localStorage.getItem("theme"); if (t === "light" || t === "dark") return t; } catch (e) {}
    return "auto";
  }
  function applyMode(mode) {
    var root = document.documentElement;
    if (mode === "light" || mode === "dark") root.setAttribute("data-theme", mode); else root.removeAttribute("data-theme");
    try { if (mode === "auto") localStorage.removeItem("theme"); else localStorage.setItem("theme", mode); } catch (e) {}
    markMode();
  }
  function markMode() {
    var m = currentMode();
    document.querySelectorAll("[data-theme-set]").forEach(function (b) { b.classList.toggle("on", b.dataset.themeSet === m); });
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-theme-set]");
    if (b) { applyMode(b.dataset.themeSet); return; }
    if (e.target.closest("[data-nav-toggle]")) { document.body.classList.toggle("nav-open"); return; }
    if (document.body.classList.contains("nav-open") && !e.target.closest(".side")) document.body.classList.remove("nav-open");
  });
  markMode();

  // Oxirgi ko'rsatilgan xabar ID si (faqat yangi xabarlarni olish uchun)
  window.lastMsgId = function () {
    var els = document.querySelectorAll("#msgs .msg");
    return els.length ? els[els.length - 1].dataset.id : 0;
  };

  window.applyTemplate = function (sel) {
    if (!sel.value) return;
    var box = document.getElementById("msg-text");
    if (box) { box.value = sel.value.split("{ism}").join(sel.dataset.name || ""); box.focus(); }
    sel.selectedIndex = 0;
  };

  function scrollDown() {
    var m = document.getElementById("msgs");
    if (m) m.scrollTop = m.scrollHeight;
  }

  function dedupe() {
    var seen = {};
    document.querySelectorAll("#msgs .msg").forEach(function (el) {
      if (seen[el.dataset.id]) el.remove();
      else seen[el.dataset.id] = true;
    });
  }

  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target && e.target.id === "msgs") {
      dedupe();
      scrollDown();
    }
  });
  window.addEventListener("load", scrollDown);

  // ---- bildirishnoma: ovoz, brauzer bildirishnomasi, sarlavhadagi son ----
  var baseTitle = document.title.replace(/^\(\d+\)\s*/, "");
  function attentionCount() {
    var n = document.getElementById("nav");
    return n ? parseInt(n.dataset.attention || "0", 10) || 0 : 0;
  }
  function updateTitle() {
    var n = attentionCount();
    document.title = (n > 0 ? "(" + n + ") " : "") + baseTitle;
  }
  document.body.addEventListener("htmx:afterSettle", updateTitle);
  window.addEventListener("load", updateTitle);
  var notifOn = false;
  try { notifOn = localStorage.getItem("notif") === "1"; } catch (e) {}
  var btn = document.getElementById("notif-btn");
  function paintBtn() {
    if (!btn) return;
    btn.classList.toggle("on", notifOn);
    btn.querySelector("span").textContent = "Bildirishnoma: " + (notifOn ? "yoqiq" : "o'chiq");
  }
  var audio = null;
  function beep() {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      if (audio.state === "suspended") audio.resume();
      var o = audio.createOscillator(), g = audio.createGain();
      o.type = "sine"; o.frequency.value = 880; g.gain.value = 0.08;
      o.connect(g); g.connect(audio.destination);
      o.start(); o.frequency.setValueAtTime(660, audio.currentTime + 0.12); o.stop(audio.currentTime + 0.28);
    } catch (e) {}
  }
  function notify(ev) {
    if (!notifOn) return;
    beep();
    try {
      if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
        new Notification("Yangi savol: " + (ev.name || "xodim"), { body: ev.preview || "" });
      }
    } catch (e) {}
  }
  if (btn) {
    paintBtn();
    btn.addEventListener("click", function () {
      notifOn = !notifOn;
      try { localStorage.setItem("notif", notifOn ? "1" : "0"); } catch (e) {}
      if (notifOn) {
        beep();
        if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
      }
      paintBtn();
    });
  }

  // Jonli hodisalar (yangi xabar, yangi so'rov va h.k.)
  var retry = 1000;
  function connect() {
    var proto = location.protocol === "https:" ? "wss" : "ws";
    var ws = new WebSocket(proto + "://" + location.host + "/ws");
    ws.onopen = function () { retry = 1000; };
    ws.onmessage = function (e) {
      var ev = {};
      try { ev = JSON.parse(e.data); } catch (_) { return; }
      htmx.trigger(document.body, "list-refresh");
      htmx.trigger(document.body, "counts-refresh");
      if (ev.type === "attention") notify(ev);
      if (ev.type === "reset") location.reload();
      var active = document.body.dataset.activeChat;
      if (active && ev.user_id && String(ev.user_id) === active) {
        htmx.trigger(document.body, "refresh-msgs");
      }
    };
    ws.onclose = function (e) {
      if (e.code === 4401) return; // kirilmagan
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 15000);
    };
    // ulanishni tirik ushlab turish
    var timer = setInterval(function () {
      if (ws.readyState === 1) ws.send("ping"); else clearInterval(timer);
    }, 25000);
  }
  if (document.querySelector(".shell")) connect();
})();
