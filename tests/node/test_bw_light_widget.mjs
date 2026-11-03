// v6: tests for bridge_warden/static/bw-light-widget.js (the "BW Light" AG Studio custom widget). Fakes only.
// Made by @Nefarious_Trey, with Grok. Copyright 2026 Trey (@Nefarious_Trey). Apache-2.0.
// Run: node tests/node/test_bw_light_widget.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const SRC = fs.readFileSync(new URL("../../bridge_warden/static/bw-light-widget.js", import.meta.url), "utf8");
const GLUE = fs.readFileSync(new URL("../../bridge_warden/static/bw-studio.js", import.meta.url), "utf8");
let pass = 0;
const t = async (name, fn) => { await fn(); pass++; console.log("ok -", name); };
const tick = () => new Promise((r) => setTimeout(r, 10));

function fakeDoc() {
  const mk = (tag) => {
    const e = {tag, children: [], attrs: {}, style: {}, listeners: {}, textContent: "", className: "", disabled: false,
      appendChild(c) { this.children.push(c); return c; },
      setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k]; },
      addEventListener(k, f) { this.listeners[k] = f; }};
    Object.defineProperty(e, "innerHTML", {set() { throw new Error("innerHTML is not allowed"); }});
    return e;
  };
  return {createElement: mk};
}
const RED = {light: "red", text: "A payment was blocked.", dot: {src: "/assets/dots/bw-dot-trey-red-full-96.png",
             src2x: "/assets/dots/bw-dot-trey-red-full-128.png"}, alt: "Red light",
             last_alert: {at: "Oct 27, 5:10 AM", text: "A payment was blocked."}, hint: "",
             can: {seen: true, fixed: false}, tokens: {seen: "T1"}};
const YELLOW = {...RED, light: "yellow", text: "Paused while you fix it.", can: {seen: false, fixed: true}, tokens: {fixed: "T2"}};

function load(states, postAnswer = {ok: true, light: "yellow", say: "The light is yellow."}) {
  const calls = [];
  let i = 0;
  // like a browser: fetch called on anything but window throws "Illegal invocation"
  const fetch = async function (url, opts = {}) {
    if (!this || !this.document) throw new TypeError("Illegal invocation");
    calls.push({url, opts});
    if (url === "/ag-studio/light.json") return {ok: true, json: async () => states[Math.min(i++, states.length - 1)]};
    return {ok: true, json: async () => postAnswer};
  };
  const ctx = {fetch, JSON, Promise, Object, String, setInterval: () => 1, clearInterval: () => {}, console};
  ctx.window = ctx; ctx.document = fakeDoc();
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  const W = ctx.BWLight;
  const shown = [];
  const w = new W.Widget();
  w.init({widgetApi: {setDisplayState: (s) => shown.push(s)}});
  return {W, w, calls, shown, ctx};
}

await t("definition has the AG Studio custom widget shape and is read-only for AI", async () => {
  const {W} = load([RED]);
  const d = W.definition();
  assert.equal(d.id, "bw-light");
  assert.equal(typeof d.comp, "function");
  assert.ok(d.defaultSize.width > 0 && d.minSize.height > 0 && d.icon.url.startsWith("/assets/dots/"));
  let asked = null;
  d.form({createDefaults: (o) => (asked = o)});
  assert.deepEqual(JSON.parse(JSON.stringify(asked)), {dataMappingItems: []});
  assert.match(d.ai.description, /Read-only/);
  assert.match(d.ai.description, /AI cannot press/);
});

await t("widgets() adds BW Light to AG Studio's built-ins and its own menu group", async () => {
  const {W} = load([RED]);
  let got = null;
  const S = {createWidgets: (o) => (got = o, {widgets: ["builtin", ...o.additionalTypes], menu: o.menu, defaultType: "grid"})};
  const r = W.widgets(S)({widgets: ["builtin"], menu: [{label: "Charts", widgetIds: ["grid"]}], defaultType: "grid"});
  assert.equal(got.additionalTypes[0].id, "bw-light");
  assert.equal(r.menu.map((m) => m.label).join(","), "Charts,Bridge Warden");
  assert.equal(JSON.stringify(r.menu[1].widgetIds), JSON.stringify(["bw-light"]));
  const r2 = W.widgets({})({widgets: ["builtin"], menu: [], defaultType: "grid"});   // no createWidgets: still works
  assert.equal(r2.widgets[1].id, "bw-light");
});

await t("shows the red light with Trey's dot, reason, last alert and only the seen button", async () => {
  const {w, shown} = load([RED]);
  await tick();
  assert.deepEqual(shown, ["displayed"]);
  assert.equal(w.getGui().attrs["data-light"], "red");
  assert.equal(w.dot.src, RED.dot.src);
  assert.equal(w.dot.attrs.srcset, RED.dot.src2x + " 2x");
  assert.equal(w.word.textContent, "Red: needs you");
  assert.equal(w.text.textContent, "A payment was blocked.");
  assert.match(w.last.textContent, /Last alert \(Oct 27, 5:10 AM\): A payment was blocked\./);
  assert.equal(w.btn.seen.disabled, false);
  assert.equal(w.btn.fixed.disabled, true);                     // red never goes straight to green
});

await t("a script or agent click (untrusted) is dropped; nothing is posted", async () => {
  const {w, calls} = load([RED]);
  await tick();
  assert.equal(w.press("seen", {isTrusted: false}), null);
  assert.equal(w.press("seen", undefined), null);
  w.btn.seen.listeners.click({isTrusted: false});
  assert.equal(calls.filter((c) => c.url === "/ag-studio/light").length, 0);
  assert.equal(w.msg.textContent, "Only you can press this button.");
});

await t("a real click posts JSON to BW's own server with the one-time token, then reloads", async () => {
  const {w, calls} = load([RED, YELLOW]);
  await tick();
  await w.press("seen", {isTrusted: true});
  const post = calls.find((c) => c.url === "/ag-studio/light");
  assert.ok(post && post.opts.method === "POST" && post.opts.credentials === "same-origin");
  assert.equal(post.opts.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(post.opts.body), {step: "seen", token: "T1"});
  assert.equal(w.msg.textContent, "The light is yellow.");
  assert.equal(w.word.textContent, "Yellow: waiting on you");
  assert.equal(w.btn.seen.disabled, true);
  assert.equal(w.btn.fixed.disabled, false);
});

await t("a step the light does not allow is never sent (fixed while red)", async () => {
  const {w, calls} = load([RED]);
  await tick();
  assert.equal(w.press("fixed", {isTrusted: true}), null);
  assert.equal(calls.filter((c) => c.url === "/ag-studio/light").length, 0);
});

await t("a refusal from the server is shown and the light is reloaded", async () => {
  const {w} = load([YELLOW], {ok: false, why: "the light is still red"});
  await tick();
  await w.press("fixed", {isTrusted: true});
  assert.equal(w.msg.textContent, "Not changed: the light is still red");
});

await t("only BW dot images are used; anything else is ignored", async () => {
  const {w} = load([{...RED, dot: {src: "https://evil.example/x.png", src2x: "javascript:alert(1)"}}]);
  await tick();
  assert.equal(w.dot.src, undefined);
  assert.equal(w.dot.attrs.srcset, undefined);
});

await t("destroy stops the refresh timer", async () => {
  const {w, ctx} = load([RED]);
  let cleared = 0;
  ctx.clearInterval = () => cleared++;
  w.destroy();
  assert.equal(cleared, 1);
  assert.equal(w.timer, null);
});

await t("no money / approve path, no AI tool, no raw HTML", async () => {
  for (const bad of ["/act", "/decide", ".click(", "submit(", "nonce", "approve", "release", "defineAiTool",
                     "innerHTML", "api.x.ai", "Authorization"]) {
    assert.ok(!SRC.includes(bad), bad);
  }
  assert.ok(SRC.includes("isTrusted"));
  assert.ok(GLUE.includes("L.widgets(S)") && GLUE.includes("'bw-light'"));
});
console.log(`${pass} passed`);
