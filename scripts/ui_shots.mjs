// Dev tool: drive headless Edge over the Chrome DevTools Protocol to look at real pages.
// Needs Node 22+ (global WebSocket and fetch), no packages. Not part of the application.
//
// 1. Start the app on scratch data (never the default data folder):
//      export KT_DATA_DIR="<scratch>/data"
//      python -m uv run manage.py migrate && python -m uv run manage.py seed_demo
//      python -m uv run manage.py runserver 127.0.0.1:8201 --noreload        (background)
// 2. Start Edge (background; stop it when you are done):
//      "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new \
//        --remote-debugging-port=9333 --user-data-dir="<scratch>/edge" --no-first-run \
//        --disable-gpu --hide-scrollbars about:blank
// 3. Write a small script next to your scratch files:
//      import { connect, login } from "<repo>/scripts/ui_shots.mjs";
//      const b = await connect();
//      const p = await b.newPage();                 // { incognito: true } = a fresh student
//      await p.dark(false);                         // this machine's system theme is dark
//      await p.viewport(390, 844);                  // true phone width; 1280, 800 for desktop
//      await login(p, "teacher", "teacher");
//      await p.goto("/teach/sessions/");
//      await p.shot("sessions-m");                  // PNG in KT_SHOTS; view it with the Read tool
//      console.log(await p.audit());                // horizontal overflow and small tap targets
//      b.close();
//    Run it with:  KT_BASE=http://127.0.0.1:8201 KT_SHOTS="<scratch>/shots" node your-script.mjs
//
// Notes: a full-page capture draws `position: sticky` bars in the middle of the page, so judge
// them with `shot(name, { full: false })`. Write scripts with an editor tool, not a bash heredoc
// (Git Bash collapses the backslashes of JS regexes).
import { mkdirSync, writeFileSync } from "node:fs";

const PORT = process.env.CDP_PORT || 9333;
export const BASE = process.env.KT_BASE || "http://127.0.0.1:8201";
export const SHOTS = process.env.KT_SHOTS || "ui-shots";

export async function connect() {
  mkdirSync(SHOTS, { recursive: true });
  const v = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
  const ws = new WebSocket(v.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = rej;
  });
  let id = 0;
  const pending = new Map();
  const listeners = [];
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id);
      pending.delete(m.id);
      m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
    } else if (m.method) {
      for (const l of [...listeners]) l(m);
    }
  };
  const send = (method, params = {}, sessionId) =>
    new Promise((res, rej) => {
      const mid = ++id;
      pending.set(mid, { res, rej });
      ws.send(JSON.stringify({ id: mid, method, params, sessionId }));
    });
  const waitEvent = (method, sessionId, timeout = 15000) =>
    new Promise((res, rej) => {
      const t = setTimeout(() => {
        listeners.splice(listeners.indexOf(l), 1);
        rej(new Error("timeout waiting for " + method));
      }, timeout);
      const l = (m) => {
        if (m.method === method && m.sessionId === sessionId) {
          clearTimeout(t);
          listeners.splice(listeners.indexOf(l), 1);
          res(m.params);
        }
      };
      listeners.push(l);
    });
  const pause = (ms) => new Promise((r) => setTimeout(r, ms));

  async function newPage({ incognito = false } = {}) {
    let browserContextId;
    if (incognito) browserContextId = (await send("Target.createBrowserContext")).browserContextId;
    const { targetId } = await send("Target.createTarget", { url: "about:blank", browserContextId });
    const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
    await send("Page.enable", {}, sessionId);
    await send("Runtime.enable", {}, sessionId);
    const page = {
      send: (m, p) => send(m, p, sessionId),
      async viewport(width, height = 844, mobile = width < 600) {
        await send(
          "Emulation.setDeviceMetricsOverride",
          { width, height, deviceScaleFactor: 1, mobile },
          sessionId
        );
        if (mobile) await send("Emulation.setTouchEmulationEnabled", { enabled: true }, sessionId);
      },
      async dark(on) {
        await send(
          "Emulation.setEmulatedMedia",
          { features: [{ name: "prefers-color-scheme", value: on ? "dark" : "light" }] },
          sessionId
        );
      },
      async goto(url) {
        const loaded = waitEvent("Page.loadEventFired", sessionId);
        await send("Page.navigate", { url: url.startsWith("http") ? url : BASE + url }, sessionId);
        await loaded;
        await pause(150);
      },
      // Evaluate JS in the page and return its (JSON-serialisable) value.
      async eval(expression) {
        const r = await send(
          "Runtime.evaluate",
          { expression, awaitPromise: true, returnByValue: true },
          sessionId
        );
        if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 600));
        return r.result.value;
      },
      // Run JS that causes a navigation (a click or a form submit) and wait for the new page.
      async act(expression) {
        const loaded = waitEvent("Page.loadEventFired", sessionId);
        await page.eval(expression);
        await loaded;
        await pause(150);
      },
      url: () => page.eval("location.pathname + location.search"),
      async shot(name, { full = true } = {}) {
        const params = { format: "png" };
        if (full) {
          const m = await send("Page.getLayoutMetrics", {}, sessionId);
          const s = m.cssContentSize;
          params.captureBeyondViewport = true;
          params.clip = { x: 0, y: 0, width: s.width, height: Math.min(s.height, 8000), scale: 1 };
        }
        const { data } = await send("Page.captureScreenshot", params, sessionId);
        writeFileSync(`${SHOTS}/${name}.png`, Buffer.from(data, "base64"));
        return name;
      },
      // Layout facts: page height, horizontal overflow, controls smaller than a tap target.
      audit: () =>
        page.eval(`(() => {
          const vw = document.documentElement.clientWidth;
          const out = { url: location.pathname, vw, scrollW: document.documentElement.scrollWidth,
            height: document.documentElement.scrollHeight, overflow: [], small: [] };
          for (const el of document.querySelectorAll('body *')) {
            const r = el.getBoundingClientRect();
            if (r.width && r.right > vw + 1 && !el.closest('.gb-scroll') && !el.closest('.visually-hidden')
                && !el.closest('thead') && getComputedStyle(el).position !== 'absolute')
              out.overflow.push(el.tagName + '.' + el.className + ' right=' + Math.round(r.right));
          }
          for (const el of document.querySelectorAll('a, button, input:not([type=hidden]), select, textarea, summary')) {
            const r = el.getBoundingClientRect();
            if (!r.width || !r.height) continue;
            if (el.closest('.visually-hidden') || el.classList.contains('skip-link')) continue;
            let h = r.height, w = r.width;
            const lab = el.closest('label');
            if (lab) { const lr = lab.getBoundingClientRect(); h = Math.max(h, lr.height); w = Math.max(w, lr.width); }
            if (h < 44 || w < 44) out.small.push(el.tagName + '[' + (el.textContent || el.name || el.type || '').trim().slice(0, 30) + '] ' + Math.round(w) + 'x' + Math.round(h));
          }
          out.overflow = out.overflow.slice(0, 10);
          return out;
        })()`),
      close: () => send("Target.closeTarget", { targetId }),
    };
    return page;
  }
  return { send, newPage, close: () => ws.close() };
}

// Log in through the real form (logs out first if this browser profile is already logged in).
export async function login(page, user, password) {
  await page.goto("/accounts/login/");
  if (!(await page.eval(`!!document.querySelector('[name=username]')`))) {
    await page.act(`document.querySelector('form[action*=logout]').submit()`);
    await page.goto("/accounts/login/");
  }
  await page.act(
    `document.querySelector('[name=username]').value=${JSON.stringify(user)};` +
      `document.querySelector('[name=password]').value=${JSON.stringify(password)};` +
      `document.querySelector('form[method=post]:not(.lang-switch)').submit()`
  );
}
