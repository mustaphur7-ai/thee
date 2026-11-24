const $ = (id) => document.getElementById(id);
let L = null, spot = null;

const fmt = (n) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const kenya = (iso) => new Date(iso).toLocaleString("en-GB", {
  timeZone: "Africa/Nairobi", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false
}) + " EAT";

async function loadLevels() {
  try {
    const r = await fetch("data/levels.json?t=" + Date.now());
    L = await r.json();
    $("analyzed").textContent = kenya(L.analyzed_at);
    $("ratio").textContent = L.gld_ratio;
    const age = (Date.now() - new Date(L.analyzed_at_utc)) / 36e5;
    const b = $("banner");
    if (L.sample) { b.hidden = false; b.textContent = "Sample data. Run the workflow once to load real levels."; }
    else if (age > 26) { b.hidden = false; b.textContent = "Stale data: the last analysis was " + Math.round(age) + " hours ago."; }
    else b.hidden = true;
    render();
  } catch (e) {
    $("banner").hidden = false;
    $("banner").textContent = "Could not load levels.json.";
  }
}

function nextRun() {
  const n = new Date();
  const t = Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), n.getUTCDate(), 14, 33, 0); // 17:33 EAT
  return t > n.getTime() ? t : t + 864e5;
}

function tick() {
  let s = Math.max(0, Math.floor((nextRun() - Date.now()) / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  $("countdown").textContent = h + "h " + String(m).padStart(2, "0") + "m " + String(s % 60).padStart(2, "0") + "s";
}

function render() {
  if (!L) return;
  const rows = {};
  const add = (label, cls, o) => {
    const key = o.price.toFixed(2);
    const r = rows[key] || (rows[key] = { price: o.price, cls, labels: [], oi: o.open_interest });
    r.labels.push(label);
  };
  add("Call wall", "res", L.call_wall);
  add("Put wall", "sup", L.put_wall);
  add("Gamma flip", "flip", { price: L.gamma_flip });
  L.resistances.forEach((o, i) => add("R" + (i + 1), "res", o));
  L.supports.forEach((o, i) => add("S" + (i + 1), "sup", o));
  const list = Object.values(rows).sort((a, b) => b.price - a.price);

  let html = "", placed = spot == null;
  const nowRow = () => '<div class="row now"><span class="name">Price now</span><span class="val">' + fmt(spot) + "</span></div>";
  for (const r of list) {
    if (!placed && r.price < spot) { html += nowRow(); placed = true; }
    const d = spot == null ? null : r.price - spot;
    const dist = d == null ? "" : (d >= 0 ? "+" : "") + fmt(d) + " (" + (d >= 0 ? "+" : "") + ((d / spot) * 100).toFixed(2) + "%)";
    const oi = r.oi ? "Open interest " + r.oi.toLocaleString("en-US") : "";
    html += '<div class="row ' + r.cls + '"><span class="name">' + r.labels.join(" + ") + '</span><span class="val">' + fmt(r.price) +
      '</span><span class="sub">' + oi + '</span><span class="dist">' + dist + "</span></div>";
  }
  if (!placed) html += nowRow();
  $("ladder").innerHTML = html;
}

async function pollSpot() {
  const sources = [
    ["https://fapi.binance.com/fapi/v1/ticker/price?symbol=XAUUSDT", "Binance XAUUSDT"],
    ["https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT", "Binance PAXGUSDT"]
  ];
  for (const [url, name] of sources) {
    try {
      const r = await fetch(url);
      if (!r.ok) continue;
      spot = parseFloat((await r.json()).price);
      $("price").textContent = fmt(spot);
      $("dot").className = "dot ok";
      $("priceMeta").textContent = name + " " + new Date().toLocaleTimeString("en-GB", { timeZone: "Africa/Nairobi" });
      render();
      return;
    } catch (e) { /* try next source */ }
  }
  $("dot").className = "dot err";
  $("priceMeta").textContent = "Price feed unavailable, retrying";
}

loadLevels(); pollSpot(); tick();
setInterval(pollSpot, 5000);
setInterval(tick, 1000);
setInterval(loadLevels, 600000);
