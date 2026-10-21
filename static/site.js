/* Shared by the marketing pages: header + footer, waitlist forms, look carousel. */
(function () {
  "use strict";
  var BRAND = "Quizclips";   // change the product name here (and in each page's <title>)
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var path = location.pathname.replace(/\/$/, "") || "/";

  var MARK = '<span class="mark" aria-hidden="true"><img src="/static/logo.svg?v=16" alt="" width="64" height="64"></span>';
  function cur(p) { return path === p ? ' aria-current="page"' : ""; }

  var SV = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
  var ICO_SET = '<a class="ico" href="/settings" aria-label="Settings"' + cur("/settings") + '>' + SV + '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg></a>';
  var ICO_USER = '<a class="ico" href="/profile" aria-label="Profile"' + cur("/profile") + '>' + SV + '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg></a>';

  var h = $("#site-header");
  if (h) h.outerHTML =
    '<header class="top"><div class="top-in">' +
    '<a class="brand" href="/">' + MARK + '<span class="name">' + BRAND + '</span></a>' +
    '<nav class="links" aria-label="Main">' +
    '<a href="/app">Studio</a><a href="/pricing"' + cur("/pricing") + '>Plans</a><a href="/#types">Video types</a><a href="/#looks">Looks</a><a href="/#faq">FAQ</a></nav>' +
    '<div class="top-end"><a class="btn btn-primary btn-sm studio-m" href="/app">Studio</a>' + ICO_SET + ICO_USER + '</div></div></header>';

  var f = $("#site-footer");
  if (f) f.outerHTML =
    '<footer class="foot"><div class="wrap"><div class="foot-in">' +
    '<div><a class="brand" href="/">' + MARK + '<span class="name">' + BRAND + '</span></a>' +
    '<p>Turn any topic into a vertical quiz video with narration, matching footage and your link on it.</p></div>' +
    '<div><h4>Product</h4><ul><li><a href="/app">Make a video</a></li><li><a href="/pricing">Plans</a></li><li><a href="/#faq">FAQ</a></li><li><a href="/settings">Settings</a></li><li><a href="/profile">Profile</a></li></ul></div>' +
    '<div><h4>Legal</h4><ul><li><a href="/terms">Terms</a></li><li><a href="/privacy">Privacy</a></li></ul></div>' +
    '</div><div class="credits">Stock footage from <a href="https://pixabay.com" rel="noopener">Pixabay</a>. Trivia questions from ' +
    '<a href="https://opentdb.com" rel="noopener">Open Trivia DB</a> (CC BY-SA 4.0). &copy; ' + new Date().getFullYear() + ' ' + BRAND + '.</div></div></footer>';

  /* waitlist forms: <form class="wl" data-waitlist data-plan="creator"> */
  document.querySelectorAll("form[data-waitlist]").forEach(function (form) {
    var msg = form.parentNode.querySelector(".wl-msg");
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = form.querySelector("button");
      msg.className = "wl-msg"; msg.textContent = "";
      btn.disabled = true;
      fetch("/api/waitlist", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: form.email.value, plan: form.dataset.plan || "", website: form.website ? form.website.value : "" })
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, d: d }; });
      }).then(function (res) {
        if (!res.ok) throw new Error(res.d.detail || "Something went wrong. Please try again.");
        form.reset(); msg.textContent = "You're on the list. We'll email you when early access opens.";
      }).catch(function (err) {
        msg.className = "wl-msg err"; msg.textContent = err.message;
      }).finally(function () { btn.disabled = false; });
    });
  });

  var held = false;   // true while the pointer is on the hero phone: the look stops changing (the clip keeps playing and the headline keeps reading)

  /* hero headline: the words light up one by one, like the narrator reading them in the videos */
  var title = $(".vtitle");
  if (title) {
    var words = title.querySelectorAll(".w");
    if (words.length && !reduce) {
      var i = -1;
      /* each word is lit for about as long as it takes to say: short words go by quickly, longer ones linger */
      var quick = { own: 130 };   // words that should go by faster than the letter count suggests
      var hold = function (w) { var t = w.textContent.replace(/[^a-z0-9]/gi, ""); return quick[t.toLowerCase()] || 95 + 42 * t.length; };
      var tick = function () {
        var wait = 300;
        if (!document.hidden) {
          words.forEach(function (w) { w.classList.remove("on"); });
          i = (i + 1) % (words.length + 1);   // one short beat with nothing lit before it starts over
          if (i < words.length) { words[i].classList.add("on"); wait = hold(words[i]); }
        }
        setTimeout(tick, wait);
      };
      tick();
    }
  }

  /* looks: the phone cycles through them, and the gallery strip shows them all */
  var screen = $("#phone-screen"), strip = $("#looks-track");
  if (screen || strip) {
    fetch("/api/looks").then(function (r) { return r.json(); }).then(function (d) {
      var list = d.looks || [];
      if (!list.length) return;
      if (screen) {
        var cap = $("#look-name"), order = list.slice();
        screen.innerHTML = "";
        var start = order.findIndex(function (l) { return l.key === d.default; });
        if (start > 0) order = order.slice(start).concat(order.slice(0, start));
        order.forEach(function (l, k) {
          var img = new Image(); img.dataset.src = "/static/looks/hd/" + l.key + ".webp"; img.alt = l.title + " look"; img.decoding = "async";
          if (k < 2) img.src = img.dataset.src;   // the full-size pictures load a couple ahead of the one showing, not all at once
          if (k === 0) img.className = "on";
          screen.appendChild(img);
        });
        var imgs = screen.querySelectorAll("img"), n = 0;
        /* the animated look showing now: its moving background and clip as a video, with the question graphics laid over it as a separate sharp picture (so the text and edges stay crisp at any video quality). Both fade over the still together. */
        var stages = [], cur = 0;
        var clipSrc = function (i) { return "/static/looks/loops/hd/" + order[i % order.length].key + ".mp4?v=4"; };
        var ovlSrc = function (i) { return "/static/looks/overlay/" + order[i % order.length].key + ".webp?v=5"; };
        var okPlay = function (v) { var pr = v.play(); if (pr && pr.catch) pr.catch(function () {}); };
        var load = function (st, i) { st.v.src = clipSrc(i); st.o.src = ovlSrc(i); st.idx = i % order.length; };
        if (!reduce) {
          for (var k = 0; k < 2; k++) {
            var el = document.createElement("div"); el.className = "pstage"; el.setAttribute("aria-hidden", "true");
            var v = document.createElement("video"); v.muted = true; v.loop = true; v.playsInline = true; v.preload = "auto";
            var o = new Image(); o.alt = ""; o.decoding = "async";
            el.appendChild(v); el.appendChild(o); screen.appendChild(el);
            stages.push({ el: el, v: v, o: o, idx: -1 });
          }
          var first = stages[0];
          first.v.addEventListener("playing", function once() { first.el.classList.add("show"); first.v.removeEventListener("playing", once); });
          load(first, 0); okPlay(first.v);
          load(stages[1], 1); stages[1].v.load();
        }
        /* the animation changes with the same 0.4s fade as the picture behind it: the next one (already loaded) fades in while the old one fades out */
        var playClip = function () {
          if (!stages.length) return;
          var old = stages[cur]; cur = 1 - cur; var st = stages[cur];
          if (st.idx !== n % order.length) load(st, n);
          try { st.v.currentTime = 0; } catch (e) {}
          okPlay(st.v); st.el.classList.add("show"); old.el.classList.remove("show");
          setTimeout(function () { if (old !== st) { old.v.pause(); load(old, n + 1); old.v.load(); } }, 450);
        };
        var setCap = function () { if (cap) cap.innerHTML = "Look: <b>" + order[n].title + "</b>"; };
        setCap();
        var link = screen.closest(".phone-link");
        var setLink = function () { if (link) link.href = "/app?look=" + encodeURIComponent(order[n].key); };   // clicking the phone opens the build page with the look showing now
        setLink();
        if (link) {   // pointing at the phone (or tabbing to it) freezes the current look until you let go
          ["mouseenter", "focus"].forEach(function (ev) { link.addEventListener(ev, function () { held = true; }); });
          ["mouseleave", "blur"].forEach(function (ev) { link.addEventListener(ev, function () { held = false; }); });
        }
        if (!reduce) setInterval(function () {
          if (document.hidden || held) return;
          imgs.forEach(function (m) { m.classList.remove("prev"); }); imgs[n].classList.remove("on"); imgs[n].classList.add("prev"); n = (n + 1) % imgs.length; imgs[n].classList.add("on"); setCap(); setLink(); playClip();
          for (var a = 1; a <= 2; a++) { var nx = imgs[(n + a) % imgs.length]; if (!nx.src) nx.src = nx.dataset.src; }
        }, 2000);
      }
      if (strip) {
        var html = list.concat(list).map(function (l, k) {
          var dup = k >= list.length;   // the second copy only exists to make the loop seamless
          return '<a class="look-tile" href="/app?look=' + l.key + '" title="Make a video in the ' + l.title + ' look"' + (dup ? ' tabindex="-1" aria-hidden="true"' : "") + '>' +
            '<img src="/static/looks/strip/' + l.key + '.webp?v=2" alt="' + (dup ? "" : l.title + " look") + '"></a>';
        }).join("");
        strip.innerHTML = html;
        /* the strip scrolls as plain pictures (smooth). Pointing at a tile plays that look's short loop in it (moving background, picture and question); moving away stops it. The strip keeps scrolling the whole time. */
        if (!reduce && window.matchMedia && matchMedia("(hover: hover) and (min-width: 901px)").matches) {
          Array.prototype.forEach.call(strip.querySelectorAll(".look-tile"), function (t, k) {
            var key = list[k % list.length].key;
            t.addEventListener("mouseenter", function () {
              var v = t._loop;
              if (!v) {
                v = t._loop = document.createElement("video");
                v.className = "tloop"; v.muted = true; v.loop = true; v.playsInline = true; v.preload = "auto"; v.disablePictureInPicture = true; v.setAttribute("aria-hidden", "true");
                v.addEventListener("playing", function () { v.classList.add("show"); });
                v.addEventListener("error", function () { v.classList.remove("show"); });
                v.src = "/static/looks/loops/strip/" + key + ".mp4?v=2";
                t.appendChild(v);
              }
              var pr = v.play(); if (pr && pr.catch) pr.catch(function () {});
            });
            t.addEventListener("mouseleave", function () {
              var v = t._loop; if (!v) return;
              v.pause(); v.classList.remove("show");
            });
          });
        }
        /* one steady speed (60 px per second = 1 px per frame on a 60 Hz screen) whatever the number of looks */
        requestAnimationFrame(function () { var half = strip.scrollWidth / 2; if (half > 0) strip.style.animationDuration = (half / 60).toFixed(2) + "s"; });
        if (reduce) strip.parentNode.setAttribute("tabindex", "0");
      }
    }).catch(function () {});
  }
})();
