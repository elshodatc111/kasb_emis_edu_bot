(function () {
  "use strict";

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
