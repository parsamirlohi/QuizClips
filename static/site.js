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
        /* the stock-video loop that plays in the picture box of the look showing now */
        var vids = [], cur = 0, vid = null, clipSrc = function (i) { return "/static/looks/clips/" + order[i % order.length].key + ".mp4"; };
        var okPlay = function (v) { var pr = v.play(); if (pr && pr.catch) pr.catch(function () {}); };
        if (!reduce) {
          for (var k = 0; k < 2; k++) {
            var v = document.createElement("video");
            v.className = "clipvid"; v.muted = true; v.loop = true; v.playsInline = true; v.setAttribute("aria-hidden", "true"); v.preload = "auto";
            screen.appendChild(v); vids.push(v);
          }
          vid = vids[0];
          vid.addEventListener("playing", function once() { vid.classList.add("show"); vid.removeEventListener("playing", once); });
          vid.src = clipSrc(0); okPlay(vid);
          vids[1].src = clipSrc(1); vids[1].load();
        }
        /* the clip changes with the same 0.4s fade as the picture behind it: the new clip (already loaded) fades in while the old one fades out */
        var playClip = function () {
          if (!vids.length) return;
          var old = vids[cur]; cur = 1 - cur; vid = vids[cur];
          var want = clipSrc(n);
          if (vid.getAttribute("src") !== want) vid.src = want;
          try { vid.currentTime = 0; } catch (e) {}
          okPlay(vid); vid.classList.add("show"); old.classList.remove("show");
          setTimeout(function () { if (old !== vid) { old.pause(); old.src = clipSrc(n + 1); old.load(); } }, 450);
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
            '<img src="/static/looks/strip/' + l.key + '.webp" alt="' + (dup ? "" : l.title + " look") + '"></a>';
        }).join("");
        strip.innerHTML = html;
        /* pointing at a tile pauses the strip and plays that look's clip in its picture box; moving away stops it. Nothing plays while the strip is just scrolling, which keeps the scroll smooth. */
        if (!reduce && window.matchMedia && matchMedia("(hover: hover) and (min-width: 901px)").matches) {
          Array.prototype.forEach.call(strip.querySelectorAll(".look-tile"), function (t, k) {
            var key = list[k % list.length].key;
            t.addEventListener("mouseenter", function () {
              var v = t._clip;
              if (!v) {
                v = t._clip = document.createElement("video");
                v.className = "tclip"; v.muted = true; v.loop = true; v.playsInline = true; v.preload = "auto"; v.setAttribute("aria-hidden", "true");
                v.addEventListener("playing", function () { v.classList.add("show"); });
                v.addEventListener("error", function () { v.classList.remove("show"); });
                v.src = "/static/looks/clips/" + key + ".mp4";
                t.appendChild(v);
              }
              var pr = v.play(); if (pr && pr.catch) pr.catch(function () {});
            });
            t.addEventListener("mouseleave", function () {
              var v = t._clip; if (!v) return;
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
