/* Bridge Warden: "Hear the call" demo in the browser (Trey, 2026-10-26).
   Demo only. Nothing happens to your money. No phone number. Nothing is sent anywhere by this page:
   the words come from the page itself (the same data as the phone call and the Worker, from notify.py).
   Optional microphone uses the browser's own speech recognition, which may send audio to the browser maker.
   It is OFF unless you tick the box. The engine part is plain and testable in node (module.exports). */
(function (root) {
  "use strict";
  function engine(D) {
    var own = function (o, k) { return Object.prototype.hasOwnProperty.call(o, k); };
    function clean(t) { return String(t == null ? "" : t).toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter(Boolean).join(" "); }
    function first(d) { return String(d == null ? "" : d).trim().slice(0, 1); }
    function matchChoice(digits, speech) {
      var d = first(digits);
      if (["1", "2", "3", "4"].indexOf(d) >= 0) return d;
      var t = clean(speech);
      if (!t) return null;
      if (own(D.solo, t)) return D.solo[t];
      var padded = " " + t + " ";
      D.filler.forEach(function (f) { padded = padded.split(" " + f + " ").join(" "); });
      var words = padded.split(" ").filter(Boolean), ords = {}, found = {}, weak = {};
      words.forEach(function (w) { if (own(D.ord, w)) ords[D.ord[w]] = 1; });
      var o = Object.keys(ords);
      if (o.length) return o.length === 1 ? o[0] : null;
      D.phrases.forEach(function (p) { if (padded.indexOf(" " + p[0] + " ") >= 0) found[p[1]] = 1; });
      words.forEach(function (w) { if (own(D.num, w)) found[D.num[w]] = 1; else if (own(D.words, w)) found[D.words[w]] = 1; });
      var f = Object.keys(found);
      if (f.length === 1) return f[0];
      if (f.length) return null;
      words.forEach(function (w) { if (own(D.weak, w)) weak[D.weak[w]] = 1; });
      var k = Object.keys(weak);
      return k.length === 1 ? k[0] : null;
    }
    var W = D.walk, S = D.situations;
    function kindOf(kind) {
      var k = own(D.kind_aliases, kind) ? D.kind_aliases[kind] : kind;
      return typeof k === "string" && own(S, k) ? k : "unauthorized";
    }
    function walkChoice(digits, speech) {
      var d = first(digits);
      if (["1", "2", "3"].indexOf(d) >= 0) return d;
      var t = clean(speech);
      if (!t) return null;
      if (own(W.solo, t)) return W.solo[t];
      var padded = " " + t + " ";
      if (padded.indexOf(" say again ") >= 0 || padded.indexOf(" one more time ") >= 0) return "2";
      var found = {};
      t.split(" ").forEach(function (w) { if (own(W.num, w)) found[W.num[w]] = 1; else if (own(W.words, w)) found[W.words[w]] = 1; });
      var f = Object.keys(found);
      return f.length === 1 ? f[0] : null;
    }
    function walkStep(kind, i, done, x, digits, speech) {
      var n = S[kind].steps.length;
      if (i >= n) return { i: i, done: done, x: 0, lead: [], finished: true };
      var c = walkChoice(digits, speech), heard = Boolean(String(digits == null ? "" : digits).trim() || clean(speech)), lead = [];
      if (c === "1") { done += "d"; i += 1; x = 0; }
      else if (c === "3") { done += "s"; i += 1; x = 0; lead = [W.skipped]; }
      else if (!heard && x >= 1) return { i: i, done: done, x: 0, lead: [D.walk_stop], finished: true };
      else if (x >= W.max_repeats) { done += "s"; i += 1; x = 0; lead = [W.move_on]; }
      else { x += 1; lead = c === "2" ? [] : [W.not_heard]; }
      return { i: i, done: done, x: x, lead: lead, finished: i >= n };
    }
    function walkSay(kind, i) {
      var st = S[kind].steps;
      return [W.step.replace("{n}", String(i + 1)).replace("{total}", String(st.length)), st[i].say, W.prompt];
    }
    function walkSummary(kind, done) {
      var st = S[kind].steps, did = [], skip = [];
      done.split("").forEach(function (c, j) { if (c === "d") did.push(st[j].short); else if (c === "s") skip.push(st[j].short); });
      var out = [W.summary_lead, did.length ? W.summary_done.replace("{list}", did.join(", ")) : W.summary_none];
      if (skip.length) out.push(W.summary_skipped.replace("{list}", skip.join(", ")));
      return out;
    }
    function walkLead(kind, test, choice) {
      var about = [D.walk_about.replace("{name}", S[kind].name.toLowerCase()), D.walk_intro];
      if (test) return (own(D.heard, choice || "") ? [D.heard[choice]] : []).concat([D.test_just, D.if_real], about);
      return (choice === "1" || choice === "2" ? [D.replies[choice][0]] : []).concat([W.lead_real], about);
    }
    // ---- one call, as a little state machine (same steps as the phone call) ----
    function end(st, lines) {
      return { say: lines.concat(st.test ? [D.safe_end] : []), st: { stage: "ended", test: st.test, kind: st.kind } };
    }
    function menuAgain(st, n, lead) {
      if (n >= 2) return end(st, [D.no_choice].concat(st.test ? [D.test_just] : []));
      return { say: [lead, D.menu], st: { stage: "menu", n: 2, test: st.test, kind: st.kind } };
    }
    function startWalk(st, choice) {
      return { say: walkLead(st.kind, st.test, choice).concat(walkSay(st.kind, 0)),
               st: { stage: "walk", i: 0, done: "", x: 0, test: st.test, kind: st.kind } };
    }
    function start(test, kind, demo) {
      test = Boolean(test || demo);
      kind = kindOf(kind);
      return { say: (demo ? [D.demo_intro] : []).concat([(test && D.open_test) || D.open, D.advice, D.menu]),
               st: { stage: "menu", n: 1, test: test, kind: kind } };
    }
    function answer(st, digits, speech) {
      if (st.stage === "menu") {
        var c = matchChoice(digits, speech);
        if (c === "4") return { say: [D.other_ask], st: { stage: "other", n: st.n, test: st.test, kind: st.kind } };
        if (st.test && (c || clean(speech))) return startWalk(st, c);
        if (!st.test && (c === "1" || c === "2")) return startWalk(st, c);
        if (!st.test && c === "3") return end(st, D.replies["3"]);
        return menuAgain(st, st.n, D.not_heard);
      }
      if (st.stage === "other") {
        var o = matchChoice(null, speech);
        if (st.test) return startWalk(st, ["1", "2", "3"].indexOf(o) >= 0 ? o : null);
        if (o === "1" || o === "2") return startWalk(st, o);
        if (o === "3") return end(st, D.replies["3"]);
        return menuAgain(st, st.n, D.other_fallback);     // no AI in the browser demo
      }
      if (st.stage === "walk") {
        var r = walkStep(st.kind, st.i, st.done, st.x, digits, speech);
        if (r.finished) {
          return end(st, r.lead.concat(walkSummary(st.kind, r.done), st.test ? [] : [W.real_end]));
        }
        return { say: r.lead.concat(walkSay(st.kind, r.i)),
                 st: { stage: "walk", i: r.i, done: r.done, x: r.x, test: st.test, kind: st.kind } };
      }
      return { say: [], st: st };
    }
    return { matchChoice: matchChoice, walkChoice: walkChoice, walkStep: walkStep, walkSummary: walkSummary,
             walkLead: walkLead, kindOf: kindOf, start: start, answer: answer };
  }

  if (typeof module !== "undefined" && module.exports) { module.exports = { engine: engine }; return; }

  // ---- the page (browser only) ----
  var doc = root.document, $ = function (id) { return doc.getElementById(id); };
  var D = JSON.parse($("bw-call-data").textContent), E = engine(D), st = null, rec = null;
  var log = $("call-log"), synth = root.speechSynthesis;
  function voice() {
    if (!synth) return null;
    var vs = synth.getVoices().filter(function (v) { return /^en/i.test(v.lang); });
    return vs.filter(function (v) { return v.localService; })[0] || vs[0] || null;   // on-device voice first
  }
  function line(who, text) {
    var li = doc.createElement("li");
    var b = doc.createElement("b"); b.textContent = who + ": ";
    li.appendChild(b); li.appendChild(doc.createTextNode(text)); log.appendChild(li);
    li.scrollIntoView({ block: "nearest" });
  }
  function speak(lines) {
    lines.forEach(function (t) { line("Bridge Warden", t); });
    if (synth && $("call-sound").checked) {
      synth.cancel();
      lines.forEach(function (t) { var u = new root.SpeechSynthesisUtterance(t); var v = voice(); if (v) u.voice = v; u.rate = 0.95; synth.speak(u); });
    }
  }
  function show() {
    var stage = st ? st.stage : "none";
    $("call-menu").hidden = !(stage === "menu");
    $("call-walk").hidden = !(stage === "walk");
    $("call-say").hidden = !(stage === "menu" || stage === "other" || stage === "walk");
    $("call-start").textContent = stage === "none" || stage === "ended" ? "Start the call" : "Start over";
    if (stage === "ended") line("Call", "The call has ended.");
  }
  function go(digits, speech, label) {
    if (!st || st.stage === "ended") return;
    line("You", label || (digits ? "pressed " + digits : (speech ? "said \u201c" + speech + "\u201d" : "(stayed quiet)")));
    var r = E.answer(st, digits, speech); st = r.st; speak(r.say); show();
  }
  $("call-start").addEventListener("click", function () {
    log.textContent = ""; if (synth) synth.cancel();
    var test = $("call-test").checked;                // a test call says it is a demo first, like a call-in
    var r = E.start(test, $("call-kind").value, test); st = r.st; speak(r.say); show();
  });
  Array.prototype.forEach.call(doc.querySelectorAll("[data-press]"), function (b) {
    b.addEventListener("click", function () { go(b.getAttribute("data-press"), "", "pressed " + b.getAttribute("data-press")); });
  });
  $("call-quiet").addEventListener("click", function () { go("", "", "(stayed quiet)"); });
  $("call-say-form").addEventListener("submit", function (ev) {
    ev.preventDefault(); var t = $("call-said").value.trim(); $("call-said").value = ""; if (t) go("", t);
  });
  var SR = root.SpeechRecognition || root.webkitSpeechRecognition;
  if (SR) {
    $("call-mic-box").hidden = false;
    $("call-mic").addEventListener("click", function () {
      if (!$("call-mic-ok").checked) { $("call-mic-note").textContent = "Tick the box first. Or just type or press a button."; return; }
      if (rec) { rec.abort(); rec = null; }
      rec = new SR(); rec.lang = "en-US"; rec.interimResults = false; rec.maxAlternatives = 1;
      rec.onresult = function (e) { var t = e.results[0][0].transcript; rec = null; go("", t); };
      rec.onerror = function () { rec = null; $("call-mic-note").textContent = "I could not hear you. Type it or press a button."; };
      $("call-mic-note").textContent = "Listening...";
      rec.onend = function () { if ($("call-mic-note").textContent === "Listening...") $("call-mic-note").textContent = ""; };
      try { rec.start(); } catch (e) { $("call-mic-note").textContent = "The microphone did not start. Type it or press a button."; }
    });
  }
  if (!synth) { $("call-sound").checked = false; $("call-sound").disabled = true; $("call-sound-note").textContent = "This browser cannot talk. The words show below."; }
  show();
})(this);
