/* Bridge Warden v6: "BW Light", an AG Studio custom widget.
   Made by @Nefarious_Trey,
   with Grok. Copyright 2026 Trey (@Nefarious_Trey). Apache-2.0 (this file only).
   Shows the account's light (red / yellow / green) with Trey's BW dots, the reason, and the last alert.
   Two owner buttons, "I've seen this" and "It's fixed", call Bridge Warden's EXISTING rules on its own server:
   - red never goes straight to green (the server refuses it);
   - agents can only raise the light: this widget gives the AI chat no tool, and it drops any click that is not a
     real person's click (event.isTrusted), so a script or agent cannot press the buttons;
   - it has no way to pay, decide a held payment or move money. Those stay with you on Home / History. */
(function (root) {
  'use strict';
  var ID = 'bw-light';
  var LABEL = {red: 'Red: needs you', yellow: 'Yellow: waiting on you', green: 'Green: all fine'};
  var BTN = {seen: "I've seen this", fixed: "It's fixed"};
  var RULES = 'Red never goes straight to green. Only you can turn it green. Agents can only raise it.';
  var LOGO = '/assets/brand/bw-mark-navy-v7b.png';
  var EVERY_MS = 15000;

  function safeImg(u) { return typeof u === 'string' && /^\/assets\/dots\/bw-dot-trey-[a-z0-9-]+\.png$/.test(u) ? u : ''; }

  function BWLightWidget() {}
  BWLightWidget.prototype.init = function (params) {
    var doc = (params && params.document) || root.document;
    this.doc = doc;
    this.api = params && params.widgetApi;
    // fetch must be called on window, not on the widget (a browser throws "Illegal invocation" otherwise)
    var get = (params && params.fetch) || root.fetch;
    this.fetch = function (url, opts) { return get.call(root, url, opts); };
    this.state = null;
    this.busy = false;
    var el = function (tag, cls, txt) {
      var e = doc.createElement(tag);
      if (cls) { e.className = cls; }
      if (txt) { e.textContent = txt; }
      return e;
    };
    var g = this.gui = el('div', 'bw-light');
    g.setAttribute('role', 'region');
    g.setAttribute('aria-label', 'BW Light');
    g.style.cssText = 'height:100%;box-sizing:border-box;display:flex;flex-direction:column;gap:8px;padding:0 0 10px;' +
      'background:#FFFFFF;color:#0B1220;font:14px system-ui,sans-serif;overflow:auto';
    var head = el('div', 'bw-light-head');
    head.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 12px;background:#FFFFFF;border-bottom:1px solid #E5E7EB';
    var logo = el('img');
    logo.src = LOGO; logo.alt = ''; logo.width = 24; logo.height = 24;
    head.appendChild(logo);
    head.appendChild(el('b', '', 'BW Light'));
    g.appendChild(head);
    var body = el('div', 'bw-light-body');
    body.style.cssText = 'display:flex;gap:12px;align-items:center;padding:2px 12px';
    this.dot = el('img', 'bw-light-dot');
    this.dot.width = 56; this.dot.height = 56;
    this.dot.alt = '';
    body.appendChild(this.dot);
    var words = el('div');
    this.word = el('div', 'bw-light-word', 'Loading the light...');
    this.word.style.cssText = 'font-size:19px;font-weight:700';
    this.word.setAttribute('role', 'status');
    this.word.setAttribute('aria-live', 'polite');
    this.text = el('div', 'bw-light-text');
    words.appendChild(this.word);
    body.appendChild(words);
    g.appendChild(body);
    this.text.style.cssText = 'padding:0 12px;font-weight:600';
    g.appendChild(this.text);
    this.last = el('div', 'bw-light-last');
    this.hint = el('div', 'bw-light-hint');
    this.last.style.cssText = this.hint.style.cssText = 'padding:0 12px;font-size:12px;color:#374151';
    g.appendChild(this.last);
    g.appendChild(this.hint);
    var row = el('div', 'bw-light-buttons');
    row.style.cssText = 'display:flex;gap:10px;padding:2px 12px';
    var self = this;
    this.btn = {};
    ['seen', 'fixed'].forEach(function (s) {
      var b = el('button', 'bw-light-' + s, BTN[s]);
      b.type = 'button';
      b.disabled = true;
      b.style.cssText = 'font:600 14px system-ui,sans-serif;padding:7px 12px;white-space:nowrap;border-radius:8px;border:1px solid #0E7490;' +
        'background:#FFFFFF;color:#0E7490;cursor:pointer';
      b.addEventListener('click', function (ev) { self.press(s, ev); });
      // In edit mode AG Studio grabs the pointer to drag the widget, and the click then arrives as an untrusted copy.
      // Keep the press on the button so your real click stays a real (trusted) click.
      var keep = function (ev) { ev.stopPropagation(); };
      b.addEventListener('pointerdown', keep);
      b.addEventListener('mousedown', keep);
      self.btn[s] = b;
      row.appendChild(b);
    });
    g.appendChild(row);
    this.msg = el('div', 'bw-light-msg');
    this.msg.style.cssText = 'padding:0 12px;font-size:13px;font-weight:600';
    this.msg.setAttribute('aria-live', 'polite');
    g.appendChild(this.msg);
    var rules = el('div', 'bw-light-rules', RULES);
    rules.style.cssText = 'padding:0 12px;font-size:11px;color:#4B5563';
    g.appendChild(rules);
    if (this.api && this.api.setDisplayState) { this.api.setDisplayState('displayed'); }
    this.load();
    if (root.setInterval) { this.timer = root.setInterval(function () { self.load(); }, EVERY_MS); }
  };
  BWLightWidget.prototype.getGui = function () { return this.gui; };
  BWLightWidget.prototype.refresh = function (params) {
    if (params && params.widgetApi) { this.api = params.widgetApi; }
    return true;
  };
  BWLightWidget.prototype.destroy = function () {
    if (this.timer && root.clearInterval) { root.clearInterval(this.timer); }
    this.timer = null;
  };
  BWLightWidget.prototype.load = function () {
    var self = this;
    return this.fetch('/ag-studio/light.json', {credentials: 'same-origin', cache: 'no-store'})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (st) { if (st) { self.show(st); } return st; })
      .catch(function () { self.word.textContent = 'Light not loaded. Home always shows it.'; return null; });
  };
  BWLightWidget.prototype.show = function (st) {
    this.state = st;
    var light = LABEL[st.light] ? st.light : 'yellow';
    this.gui.setAttribute('data-light', light);
    var src = safeImg(st.dot && st.dot.src), src2 = safeImg(st.dot && st.dot.src2x);
    if (src) { this.dot.src = src; }
    if (src2) { this.dot.setAttribute('srcset', src2 + ' 2x'); }
    this.dot.alt = String(st.alt || LABEL[light]);
    this.word.textContent = LABEL[light];
    this.text.textContent = String(st.text || '');
    var la = st.last_alert;
    this.last.textContent = la ? ('Last alert' + (la.at ? ' (' + la.at + ')' : '') + ': ' + short(la.text, 160)) : 'No red alert yet.';
    this.hint.textContent = String(st.hint || '');
    var can = st.can || {}, keys = st.tokens || {};
    for (var s in this.btn) {
      if (Object.prototype.hasOwnProperty.call(this.btn, s)) {
        this.btn[s].disabled = this.busy || !(can[s] && keys[s]);
      }
    }
  };
  // Only a real person's click counts. A script, an agent or a scripted click makes an untrusted event and is dropped.
  BWLightWidget.prototype.press = function (step, ev) {
    if (!ev || ev.isTrusted !== true) { this.msg.textContent = 'Only you can press this button.'; return null; }
    var st = this.state;
    if (this.busy || !st || !st.can || !st.can[step] || !st.tokens || !st.tokens[step]) { return null; }
    this.busy = true;
    for (var s in this.btn) { if (Object.prototype.hasOwnProperty.call(this.btn, s)) { this.btn[s].disabled = true; } }
    var self = this;
    return this.fetch('/ag-studio/light', {
      method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({step: step, token: st.tokens[step]})
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (r) {
        self.msg.textContent = r && r.ok ? String(r.say || ('Done. The light is now ' + r.light + '.')) : ('Not changed: ' + ((r && r.why) || 'try again'));
      })
      .catch(function () { self.msg.textContent = 'Not changed: no answer from Bridge Warden.'; })
      .then(function () { self.busy = false; return self.load(); });
  };

  function short(t, n) { t = String(t || ''); return t.length > n ? t.slice(0, n - 3) + '...' : t; }
  function definition() {
    return {
      id: ID,
      label: 'BW Light',
      icon: {url: '/assets/dots/bw-dot-trey-green-full-96.png'},
      form: function (p) { return p.createDefaults({dataMappingItems: []}); },
      comp: BWLightWidget,
      defaultSize: {width: 420, height: 360},
      minSize: {width: 300, height: 280},
      ai: {description: 'Read-only display of the Bridge Warden account light (red, yellow or green), its reason and ' +
                        'the last alert. Its buttons are for the owner only; AI cannot press them.'}
    };
  }
  // The AG Studio "widgets" property: all built-in widgets, plus BW Light in its own menu group.
  function widgets(S) {
    return function (wc) {
      var menu = (wc && wc.menu ? wc.menu : []).concat([{label: 'Bridge Warden', widgetIds: [ID]}]);
      if (S && S.createWidgets) { return S.createWidgets({additionalTypes: [definition()], menu: menu}); }
      return {widgets: (wc.widgets || []).concat([definition()]), menu: menu, defaultType: wc.defaultType};
    };
  }
  var api = {ID: ID, LABEL: LABEL, RULES: RULES, Widget: BWLightWidget, definition: definition, widgets: widgets};
  root.BWLight = api;
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
})(typeof window !== 'undefined' ? window : globalThis);
