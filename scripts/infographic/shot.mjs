// Screenshot an HTML file through the Chrome DevTools Protocol.
// usage: node shot.mjs <file.html> <out.png> [width] [scale]
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const [, , htmlPath, outPath, widthArg, scaleArg] = process.argv;
const width = Number(widthArg || 1500);
const scale = Number(scaleArg || 2);
const chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = path.resolve(".infographic/chrome-profile-cdp");
fs.rmSync(profile, { recursive: true, force: true });
fs.mkdirSync(profile, { recursive: true });

const proc = spawn(chrome, [
  "--headless=new",
  "--disable-gpu",
  "--no-sandbox",
  "--hide-scrollbars",
  "--no-first-run",
  "--no-default-browser-check",
  "--disable-extensions",
  "--remote-debugging-port=0",
  `--user-data-dir=${profile}`,
  "about:blank",
], { stdio: ["ignore", "ignore", "pipe"] });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getPort() {
  const file = path.join(profile, "DevToolsActivePort");
  for (let i = 0; i < 150; i++) {
    if (fs.existsSync(file)) {
      const txt = fs.readFileSync(file, "utf8").split("\n");
      if (txt[0]) return Number(txt[0]);
    }
    await sleep(100);
  }
  throw new Error("no devtools port");
}

const port = await getPort();
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

let id = 0;
const pending = new Map();
const events = new Map();
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { res, rej } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
  } else if (msg.method) {
    const list = events.get(msg.method) || [];
    list.forEach((fn) => fn(msg.params));
    events.delete(msg.method);
  }
};
const send = (method, params = {}) =>
  new Promise((res, rej) => {
    const mid = ++id;
    pending.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
const once = (method) =>
  new Promise((res) => {
    const list = events.get(method) || [];
    list.push(res);
    events.set(method, list);
  });

await send("Page.enable");
await send("Runtime.enable");
const loaded = once("Page.loadEventFired");
await send("Page.navigate", { url: `file://${path.resolve(htmlPath)}` });
await loaded;
await sleep(700);

const metrics = await send("Runtime.evaluate", {
  expression: `(() => {
    const page = document.querySelector('.page');
    const svgs = [...document.querySelectorAll('svg.chart')].map(s => {
      const r = s.getBoundingClientRect();
      return {w: Math.round(r.width), h: Math.round(r.height)};
    });
    const rects = [...document.querySelectorAll('section, footer, .kpis, .split > .panel')].map(el => {
      const r = el.getBoundingClientRect();
      return {tag: el.tagName + '.' + el.className.split(' ')[0], y: Math.round(r.top), h: Math.round(r.height)};
    });
    return JSON.stringify({height: Math.ceil(page.getBoundingClientRect().height),
      width: document.documentElement.scrollWidth, svgs, rects,
      fonts: getComputedStyle(document.querySelector('h1')).fontFamily});
  })()`,
  returnByValue: true,
});
const info = JSON.parse(metrics.result.value);
const height = info.height + 24;

await send("Emulation.setDeviceMetricsOverride", {
  width, height, deviceScaleFactor: scale, mobile: false,
});
await sleep(400);
const shot = await send("Page.captureScreenshot", {
  format: "png", captureBeyondViewport: true, fromSurface: true,
  clip: { x: 0, y: 0, width, height, scale: 1 },
});
fs.writeFileSync(outPath, Buffer.from(shot.data, "base64"));
console.log(JSON.stringify(info));
console.log(`saved ${outPath} @ ${width}x${height} x${scale}`);

await send("Browser.close").catch(() => {});
ws.close();
proc.kill();
process.exit(0);
