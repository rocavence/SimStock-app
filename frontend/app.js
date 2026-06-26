const $ = (s) => document.querySelector(s);
const fmt = (n, d = 0) => n == null ? "—" : Number(n).toLocaleString("zh-TW", { minimumFractionDigits: d, maximumFractionDigits: d });
const cls = (n) => n == null ? "" : n > 0 ? "up" : n < 0 ? "down" : "";
const sign = (n, d = 0) => n == null ? "—" : (n > 0 ? "+" : "") + fmt(n, d);

let side = "buy", lot = "round";
let SETTINGS = null;
let current = null;        // 目前查詢的證券 {code,name,sec_type,market}
let quoteTimer = null;     // 報價卡即時刷新計時器
let lastPrice = null;      // 用於價格跳動 flash
let marketOpen = false;
let lastPortfolio = null;  // 最新帳戶快照（含可預約資金）

async function api(path, method = "GET", body) {
  const r = await fetch("/api" + path, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || "錯誤");
  return data;
}

/* ---------- 分段選擇器 ---------- */
function activate(sel, v) {
  document.querySelectorAll(`${sel} button`).forEach((x) => x.classList.toggle("active", x.dataset.v === v));
}
function setSide(v) { side = v; activate("#o-side", v); updateEstimate(); syncSubmitBtn(); }
function setLot(v) {
  lot = v; activate("#o-lot", v);
  $("#o-qty").placeholder = v === "round" ? "張數" : "股數 1~999";
  updateEstimate(); syncSubmitBtn();
}
document.querySelectorAll("#o-side button").forEach((b) => (b.onclick = () => setSide(b.dataset.v)));
document.querySelectorAll("#o-lot button").forEach((b) => (b.onclick = () => setLot(b.dataset.v)));

/* ---------- 時鐘 ---------- */
setInterval(() => {
  const d = new Date();
  $("#clock").textContent = d.toLocaleTimeString("zh-TW", { hour12: false });
}, 1000);

/* ---------- 查詢報價 ---------- */
async function lookup(code) {
  const msg = $("#lookup-msg"); msg.className = "msg"; msg.textContent = "查詢中…";
  try {
    const d = await api("/quote/" + encodeURIComponent(code));
    if (!d.quote) throw new Error("查無報價");
    current = d.security; lastPrice = null;
    msg.textContent = "";
    renderQuote(d.quote);
    $("#quote-card").classList.remove("hidden");
    loadChart(current.code);
    startQuoteRefresh(code);
    updateEstimate();
  } catch (e) {
    msg.className = "msg err"; msg.textContent = "✕ " + e.message;
    $("#quote-card").classList.add("hidden"); current = null; stopQuoteRefresh();
  }
}
/* ---------- K 線圖 ---------- */
let chart = null, candleSeries = null;
function ensureChart() {
  if (chart || !window.LightweightCharts) return;
  const el = $("#qc-chart");
  chart = LightweightCharts.createChart(el, {
    width: el.clientWidth, height: 220, autoSize: true,
    layout: { background: { color: "transparent" }, textColor: "#828a98", fontFamily: "IBM Plex Mono, monospace" },
    grid: { vertLines: { color: "rgba(255,255,255,.04)" }, horzLines: { color: "rgba(255,255,255,.04)" } },
    rightPriceScale: { borderColor: "#232932" },
    timeScale: { borderColor: "#232932", timeVisible: false },
    crosshair: { mode: 0 },
  });
  candleSeries = chart.addCandlestickSeries({
    upColor: "#e08a90", downColor: "#76c2a4",       // 台股紅漲綠跌（柔和）
    borderUpColor: "#e08a90", borderDownColor: "#76c2a4",
    wickUpColor: "#e08a90", wickDownColor: "#76c2a4",
  });
  new ResizeObserver(() => { if (chart) chart.applyOptions({ width: el.clientWidth }); }).observe(el);
}
async function loadChart(code) {
  ensureChart();
  if (!candleSeries) return;
  try {
    const d = await api("/history/" + encodeURIComponent(code));
    candleSeries.setData(d.candles || []);
    chart.timeScale().fitContent();
  } catch {}
}

function startQuoteRefresh(code) {
  stopQuoteRefresh();
  quoteTimer = setInterval(async () => {
    try { const d = await api("/quote/" + encodeURIComponent(code)); if (d.quote) renderQuote(d.quote); } catch {}
  }, 5000);
}
function stopQuoteRefresh() { if (quoteTimer) clearInterval(quoteTimer); quoteTimer = null; }

function renderQuote(q) {
  current._quote = q;
  $("#qc-name").textContent = current.name;
  $("#qc-code").textContent = current.code;
  const typeTag = { stock: "股票", etf: "ETF", bond_etf: "債券ETF" }[current.sec_type] || "";
  $("#qc-type").textContent = typeTag;

  const last = $("#qc-last"); last.textContent = fmt(q.price, 2);
  const chg = q.price != null && q.prev_close != null ? q.price - q.prev_close : null;
  const pct = chg != null && q.prev_close ? chg / q.prev_close * 100 : null;
  last.className = ""; last.classList.add(cls(chg));
  $("#qc-chg").textContent = chg == null ? "—" : `${sign(chg, 2)}　${sign(pct, 2)}%`;
  $("#qc-chg").className = "qc-chg " + cls(chg);

  // 價格跳動 flash
  if (lastPrice != null && q.price != null && q.price !== lastPrice) {
    const f = q.price > lastPrice ? "flash-up" : "flash-down";
    last.classList.remove("flash-up", "flash-down"); void last.offsetWidth; last.classList.add(f);
  }
  lastPrice = q.price;

  $("#qc-limup").textContent = fmt(q.limit_up, 2);
  $("#qc-limdn").textContent = fmt(q.limit_down, 2);
  if (q.limit_up && q.limit_down && q.price != null) {
    const pos = Math.max(0, Math.min(100, (q.price - q.limit_down) / (q.limit_up - q.limit_down) * 100));
    $("#qc-marker").style.left = pos + "%";
  }
  $("#qc-bid").textContent = fmt(q.bid, 2);
  $("#qc-ask").textContent = fmt(q.ask, 2);
  $("#qc-open").textContent = fmt(q.open, 2);
  $("#qc-high").textContent = fmt(q.high, 2);
  $("#qc-low").textContent = fmt(q.low, 2);
  updateEstimate();
}

/* ---------- 可賣數量 ---------- */
function holdingShares(code) {
  const ps = lastPortfolio && lastPortfolio.positions;
  const h = ps && ps.find((p) => p.code === code);
  return h ? h.shares : 0;
}
function maxSellableQty() {
  const sh = current ? holdingShares(current.code) : 0;
  if (sh <= 0) return 0;
  return lot === "round" ? Math.floor(sh / 1000) : Math.min(sh, 999);
}
function updateSellable() {
  const box = $("#o-sellable");
  const sh = side === "sell" && current ? holdingShares(current.code) : 0;
  if (sh <= 0) { box.classList.add("hidden"); return; }
  $("#o-max").textContent = `${fmt(maxSellableQty())} ${lot === "round" ? "張" : "股"}`;
  box.classList.remove("hidden");
}

/* ---------- 成本試算（參考用） ---------- */
function updateEstimate() {
  const el = $("#o-estimate");
  const submit = $("#o-submit");
  submit.disabled = false;
  updateSellable();
  if (!current || !current._quote || !SETTINGS) { el.textContent = "—"; return; }
  const price = $("#o-price").value ? Number($("#o-price").value) : current._quote.price;
  const qty = Number($("#o-qty").value) || 0;
  if (!price || !qty) { el.textContent = "—"; return; }
  const shares = lot === "round" ? qty * 1000 : qty;
  const gross = price * shares;
  const feeRate = +SETTINGS.fee_rate * +SETTINGS.fee_discount;
  const feeMin = +(lot === "round" ? SETTINGS.fee_min_round : SETTINGS.fee_min_odd);
  const fee = Math.max(Math.floor(gross * feeRate), feeMin);

  if (side === "buy") {
    const need = gross + fee;
    let line = `預估：${fmt(shares)} 股 × ${fmt(price, 2)} ＝ <b>${fmt(gross)}</b>＋手續費 ${fmt(fee)}　應付 <b>${fmt(need)}</b>`;
    // 收盤＝預約模式：檢查可預約資金
    if (!marketOpen && lastPortfolio && lastPortfolio.started) {
      const avail = lastPortfolio.reservable_cash;
      if (need > avail) {
        line += `<br><span class="warn-text">⚠ 可預約資金僅 ${fmt(avail)}，不足以預約此單</span>`;
        submit.disabled = true;
      } else {
        line += `<br><span class="dim">可預約資金 ${fmt(avail)}（預約後剩 ${fmt(avail - need)}）</span>`;
      }
    } else if (marketOpen && lastPortfolio && lastPortfolio.started && need > lastPortfolio.cash) {
      line += `<br><span class="warn-text">⚠ 現金僅 ${fmt(lastPortfolio.cash)}，不足以買進</span>`;
      submit.disabled = true;
    }
    el.innerHTML = line;
  } else {
    const taxRate = current.sec_type === "bond_etf" ? 0 : +(current.sec_type === "etf" ? SETTINGS.etf_tax_rate : SETTINGS.tax_rate);
    const tax = Math.floor(gross * taxRate);
    let line = `預估：賣 ${fmt(shares)} 股 ＝ ${fmt(gross)}－費 ${fmt(fee)}－稅 ${fmt(tax)}　實收 <b>${fmt(gross - fee - tax)}</b>`;
    const held = holdingShares(current.code);
    if (held <= 0) {
      line += `<br><span class="warn-text">⚠ 未持有此檔，無法賣出</span>`; submit.disabled = true;
    } else if (shares > held) {
      line += `<br><span class="warn-text">⚠ 持股僅 ${fmt(held)} 股，最多可賣 ${fmt(maxSellableQty())} ${lot === "round" ? "張" : "股"}</span>`;
      submit.disabled = true;
    }
    el.innerHTML = line;
  }
}
$("#o-qty").addEventListener("input", updateEstimate);
$("#o-price").addEventListener("input", updateEstimate);
$("#o-max-btn").onclick = () => { $("#o-qty").value = maxSellableQty(); updateEstimate(); };

/* 依市場開盤狀態切換送出鈕文案/顏色 */
function syncSubmitBtn() {
  const b = $("#o-submit");
  b.className = "btn-trade " + side;
  b.textContent = marketOpen ? (side === "buy" ? "買進送出" : "賣出送出")
                             : (side === "buy" ? "預約買進（開盤成交）" : "預約賣出（開盤成交）");
}

/* ---------- 送出委託 ---------- */
$("#o-submit").onclick = async () => {
  if (!current) return;
  const msg = $("#order-msg"); msg.className = "msg info"; msg.textContent = "送出中…";
  try {
    const priceVal = $("#o-price").value;
    const res = await api("/order", "POST", {
      code: current.code, side, lot_type: lot,
      quantity: Number($("#o-qty").value),
      limit_price: priceVal ? Number(priceVal) : null,
    });
    if (res.pending) {
      msg.className = "msg info"; msg.textContent = "🕓 " + res.message;
    } else {
      const o = res.order;
      msg.className = "msg ok";
      msg.textContent = `✓ 成交 ${o.name} ${o.side === "buy" ? "買" : "賣"} ${fmt(o.shares)} 股 @ ${fmt(o.price, 2)}，費 ${fmt(o.fee)}${o.tax ? `／稅 ${fmt(o.tax)}` : ""}`;
    }
    refreshAll();
  } catch (e) { msg.className = "msg err"; msg.textContent = "✕ " + e.message; }
};

$("#lookup-btn").onclick = () => { const c = $("#o-code").value.trim(); if (c) lookup(c); };
$("#o-code").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#lookup-btn").click(); });

/* ---------- 帳戶 / 存款 ---------- */
async function deposit(amount) {
  if (!amount || amount <= 0) { alert("請輸入大於 0 的金額"); return; }
  await api("/account/deposit", "POST", { amount });
  $("#deposit-input").value = ""; $("#add-deposit").value = "";
  refreshStatus();
}
$("#deposit-start-btn").onclick = () => deposit(Number($("#deposit-input").value));
$("#add-deposit-btn").onclick = () => deposit(Number($("#add-deposit").value));
$("#deposit-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#deposit-start-btn").click(); });

/* ---------- 刪除確認（反覆警告） ---------- */
const overlay = $("#reset-overlay");
$("#reset-btn").onclick = () => {
  $("#rd-step2").classList.add("hidden");
  $("#rd-next").textContent = "我了解，繼續";
  $("#rd-next").disabled = false;
  $("#rd-confirm").value = "";
  overlay.classList.remove("hidden");
};
$("#rd-cancel").onclick = () => overlay.classList.add("hidden");
overlay.onclick = (e) => { if (e.target === overlay) overlay.classList.add("hidden"); };
$("#rd-next").onclick = async () => {
  const step2 = $("#rd-step2");
  if (step2.classList.contains("hidden")) {       // 第一段 → 進入第二段
    step2.classList.remove("hidden");
    $("#rd-next").textContent = "永久刪除";
    $("#rd-next").disabled = true;
    $("#rd-confirm").focus();
  } else {                                         // 第二段 → 真正刪除
    await api("/account/reset", "POST");
    overlay.classList.add("hidden");
    current = null; stopQuoteRefresh(); $("#quote-card").classList.add("hidden");
    refreshAll();
  }
};
$("#rd-confirm").addEventListener("input", (e) => {
  $("#rd-next").disabled = e.target.value.trim() !== "刪除";
});

/* ---------- 自選股 ---------- */
$("#w-add").onclick = async () => {
  const raw = $("#w-code").value.trim(); if (!raw) return;
  const codes = raw.split(/[\s,，、]+/).filter(Boolean);
  try {
    const r = await api("/watchlist/bulk", "POST", { codes });
    $("#w-code").value = "";
    refreshWatch();
    if (r.notfound && r.notfound.length) alert("查無：" + r.notfound.join("、"));
  } catch (e) { alert(e.message); }
};
$("#w-code").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#w-add").click(); });

/* ---------- 畫面渲染 ---------- */
function renderSummary(p) {
  $("#start-hero").classList.toggle("hidden", p.started);
  $("#summary").classList.toggle("hidden", !p.started);
  if (!p.started) return;
  $("#s-total").textContent = fmt(p.total_assets);
  $("#s-cash").textContent = fmt(p.cash);
  $("#s-mv").textContent = fmt(p.market_value);
  const unreal = p.positions.reduce((a, x) => a + (x.unrealized || 0), 0);
  setStat("#s-unreal", sign(unreal), cls(unreal));
  setStat("#s-real", sign(p.realized_pnl), cls(p.realized_pnl));
  setStat("#s-pnl", `${sign(p.total_pnl)}（${sign(p.total_pnl_pct, 2)}%）`, cls(p.total_pnl));
  $("#s-initial").textContent = "NT$ " + fmt(p.initial_deposit);
  const sub = $("#pending-sub");
  if (p.pending_reserved > 0) sub.innerHTML = `／ 已預留 <b>${fmt(p.pending_reserved)}</b>，可再預約 <b>${fmt(p.reservable_cash)}</b>`;
  else sub.textContent = "／ 收盤下單，開盤成交";
}
function setStat(sel, text, c) { const el = $(sel); el.textContent = text; el.className = (sel === "#s-pnl" ? "stat-sub " : "") + c; }

function renderHoldings(positions) {
  const tb = $("#holdings-body");
  if (!positions.length) { tb.innerHTML = `<tr class="empty-row"><td colspan="9">尚無持股，查詢代碼即可下單</td></tr>`; return; }
  tb.innerHTML = positions.map((p) => `
    <tr>
      <td>${p.code}</td><td>${p.name}</td>
      <td>${fmt(p.shares)}</td><td>${fmt(p.avg_cost, 2)}</td><td>${fmt(p.price, 2)}</td>
      <td>${fmt(p.market_value)}</td>
      <td class="${cls(p.unrealized)}">${sign(p.unrealized)}</td>
      <td class="${cls(p.unrealized_pct)}">${sign(p.unrealized_pct, 2)}%</td>
      <td><button class="sell-btn" data-code="${p.code}" data-shares="${p.shares}">賣出</button></td>
    </tr>`).join("");
  tb.querySelectorAll(".sell-btn").forEach((b) => b.onclick = () =>
    sellHolding(b.dataset.code, Number(b.dataset.shares)));
}

/* 從庫存一鍵賣出：帶入下單區、切賣出、預填股數，估算手續費＋稅（粗估） */
async function sellHolding(code, shares) {
  $("#o-code").value = code;
  await lookup(code);
  setSide("sell");
  if (shares % 1000 === 0) { setLot("round"); $("#o-qty").value = shares / 1000; }
  else if (shares < 1000) { setLot("odd"); $("#o-qty").value = shares; }
  else { setLot("round"); $("#o-qty").value = Math.floor(shares / 1000); }
  updateEstimate();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function refreshStatus() {
  try {
    const s = await api("/status");
    lastPortfolio = s.portfolio;
    marketOpen = s.market.any_open; syncSubmitBtn();
    const badge = $("#market-badge");
    const label = s.market.any_open ? "盤中交易" : (s.market.is_trading_day ? "非交易時段" : "今日休市");
    badge.querySelector("b").textContent = label;
    badge.className = "status-pill " + (s.market.any_open ? "open" : "closed");
    $("#last-poll").textContent = s.last_poll;
    if (s.save) {
      $("#ds-path").textContent = s.save.path;
      $("#ds-ts").textContent = s.save.ts ? "　最後存檔 " + s.save.ts.replace("T", " ") : "";
    }
    renderSummary(s.portfolio);
    renderHoldings(s.portfolio.positions);
    updateEstimate();   // 可預約資金即時反映
  } catch {}
}

async function refreshWatch() {
  const list = await api("/watchlist");
  const tb = $("#watch-body");
  if (!list.length) { tb.innerHTML = `<tr class="empty-row"><td colspan="4">尚無自選（會本地保存）</td></tr>`; renderTicker([]); return; }
  tb.innerHTML = list.map((w) => {
    const q = w.quote || {};
    const chg = q.price != null && q.prev_close != null ? q.price - q.prev_close : null;
    const pct = chg != null && q.prev_close ? chg / q.prev_close * 100 : null;
    return `<tr data-code="${w.code}">
      <td>${w.code} ${w.name}</td>
      <td class="${cls(chg)}">${fmt(q.price, 2)}</td>
      <td class="${cls(chg)}">${sign(pct, 2)}%</td>
      <td><span class="x-del" data-code="${w.code}">✕</span></td>
    </tr>`;
  }).join("");
  tb.querySelectorAll("tr[data-code]").forEach((tr) => tr.onclick = (e) => {
    if (e.target.classList.contains("x-del")) return;
    $("#o-code").value = tr.dataset.code; lookup(tr.dataset.code);
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  tb.querySelectorAll(".x-del").forEach((x) => x.onclick = async (e) => {
    e.stopPropagation(); await api("/watchlist/" + x.dataset.code, "DELETE"); refreshWatch();
  });
  renderTicker(list);
}

function renderTicker(list) {
  const valid = list.filter((w) => w.quote && w.quote.price != null);
  const track = $("#ticker-track");
  if (!valid.length) { $("#ticker").style.display = "none"; return; }
  $("#ticker").style.display = "block";
  const item = (w) => {
    const q = w.quote, chg = q.price - (q.prev_close || q.price);
    const c = chg > 0 ? "up" : chg < 0 ? "down" : "";
    return `<span class="ti">${w.code} ${w.name} <b class="${c}">${fmt(q.price, 2)}</b><span class="${c}">${sign(chg, 2)}</span></span>`;
  };
  const html = valid.map(item).join("");
  track.innerHTML = html + html;   // 重複一份做無縫循環
}

async function refreshPending() {
  const list = await api("/pending");
  const box = $("#pending-list");
  const active = list.filter((p) => p.status === "pending");
  const recent = list.filter((p) => p.status !== "pending").slice(0, 3);
  const rows = [...active, ...recent];
  if (!rows.length) { box.innerHTML = `<p class="empty">無預約委託</p>`; return; }
  box.innerHTML = rows.map((p) => {
    const sideTxt = `<span class="s-${p.side}">${p.side === "buy" ? "買" : "賣"}</span>`;
    const qty = p.lot_type === "round" ? `${p.quantity} 張` : `${p.quantity} 股`;
    const price = p.limit_price ? `限 ${fmt(p.limit_price, 2)}` : "市價";
    const statusTxt = { pending: "等待開盤", filled: "✓ 已成交", failed: "✕ " + p.note, cancelled: "已取消" }[p.status];
    const statusCls = p.status === "failed" ? "down" : p.status === "filled" ? "up" : "dim";
    return `<div class="po ${p.status}">
      <div class="po-main">${sideTxt} ${p.name} <span class="mono">${qty}・${price}</span>
        <div class="po-note ${statusCls}">${statusTxt}</div></div>
      ${p.status === "pending" ? `<button class="po-cancel" data-id="${p.id}">取消</button>` : ""}
    </div>`;
  }).join("");
  box.querySelectorAll(".po-cancel").forEach((b) => b.onclick = async () => {
    await api("/pending/" + b.dataset.id, "DELETE"); refreshPending();
  });
}

async function refreshTx() {
  const tx = await api("/transactions");
  const tb = $("#tx-body");
  if (!tx.length) { tb.innerHTML = `<tr class="empty-row"><td colspan="10">尚無交易（會本地保存，直到你手動清空）</td></tr>`; return; }
  tb.innerHTML = tx.map((t) => `
    <tr>
      <td>${t.ts.slice(5)}</td><td>${t.code} ${t.name}</td>
      <td class="${t.side === "buy" ? "up" : "down"}">${t.side === "buy" ? "買" : "賣"}</td>
      <td>${t.lot_type === "round" ? "整股" : "零股"}</td>
      <td>${fmt(t.shares)}</td><td>${fmt(t.price, 2)}</td>
      <td>${fmt(t.fee)}</td><td>${fmt(t.tax)}</td>
      <td class="${cls(t.net)}">${sign(t.net)}</td>
      <td class="${cls(t.realized)}">${t.realized ? sign(t.realized) : "—"}</td>
    </tr>`).join("");
}

async function refreshScenarios() {
  try {
    const d = await api("/scenarios");
    $("#scen-sub").innerHTML = `／ 同樣 ${fmt(d.capital)} 起跑，自 ${d.created}`;
    const pcts = d.baskets.map((b) => b.pnl_pct);
    const best = Math.max(...pcts), worst = Math.min(...pcts);
    $("#scen-cards").innerHTML = d.baskets.map((b) => {
      const win = b.pnl_pct === best && best !== worst;
      const holds = b.holdings.map((h) =>
        `<div class="sc-hold"><span>${h.code} ${h.name}</span>
         <span class="${cls(h.pnl_pct)}">${fmt(h.price, 2)}　${sign(h.pnl_pct, 2)}%</span></div>`).join("");
      return `<div class="scen-card ${win ? "win" : ""}">
        ${win ? '<span class="badge-win">領先</span>' : ""}
        <h4>${b.label}</h4><div class="sc-desc">${b.desc}</div>
        <div class="sc-ret ${cls(b.pnl)}">${sign(b.pnl_pct, 2)}%</div>
        <div class="sc-val">投入 ${fmt(b.invested)}　現值 ${fmt(b.current)}　損益 ${sign(b.pnl)}</div>
        ${holds}</div>`;
    }).join("");
    const diff = (best - worst).toFixed(2);
    if (d.baskets.length > 1) $("#scen-diff").textContent = `兩組目前差距 ${diff} 個百分點`;
    if (!$("#tab-scen").classList.contains("hidden")) renderScenTrend(d.history || []);
  } catch {}
}

let scenChart = null, scenLines = null;
function renderScenTrend(history) {
  if (!window.LightweightCharts) return;
  const el = $("#scen-chart");
  if (!scenChart) {
    scenChart = LightweightCharts.createChart(el, {
      width: el.clientWidth, height: 240, autoSize: true,
      layout: { background: { color: "transparent" }, textColor: "#828a98", fontFamily: "IBM Plex Mono, monospace" },
      grid: { vertLines: { color: "rgba(255,255,255,.04)" }, horzLines: { color: "rgba(255,255,255,.04)" } },
      rightPriceScale: { borderColor: "#232932" }, timeScale: { borderColor: "#232932" },
    });
    scenLines = {
      balanced: scenChart.addLineSeries({ color: "#5b9cf0", lineWidth: 2 }),
      yolo: scenChart.addLineSeries({ color: "#f0606f", lineWidth: 2 }),
    };
    new ResizeObserver(() => { if (scenChart) scenChart.applyOptions({ width: el.clientWidth }); }).observe(el);
  }
  scenLines.balanced.setData(history.map((h) => ({ time: h.date, value: h.balanced ?? 0 })));
  scenLines.yolo.setData(history.map((h) => ({ time: h.date, value: h.yolo ?? 0 })));
  scenChart.timeScale().fitContent();
}

/* 分頁切換 */
document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
  $("#tab-" + b.dataset.tab).classList.remove("hidden");
  if (b.dataset.tab === "scen") refreshScenarios();
});

/* 讀入投資資訊（記住路徑） */
$("#import-toggle").onclick = () => {
  const inp = $("#import-path"), go = $("#import-go");
  const showing = !inp.classList.contains("hidden");
  inp.classList.toggle("hidden", showing);
  go.classList.toggle("hidden", showing);
  if (!showing) inp.focus();
};
$("#import-go").onclick = async () => {
  const path = $("#import-path").value.trim();
  if (!path) return;
  const msg = $("#import-msg"); msg.className = "ds-msg"; msg.textContent = "讀入中…";
  try {
    await api("/import", "POST", { path });
    msg.className = "ds-msg ok"; msg.textContent = "✓ 已讀入並記住路徑";
    $("#import-path").value = ""; $("#import-path").classList.add("hidden"); $("#import-go").classList.add("hidden");
    refreshAll();
    setTimeout(() => { msg.textContent = ""; }, 4000);
  } catch (e) { msg.className = "ds-msg err"; msg.textContent = "✕ " + e.message; }
};
$("#import-path").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#import-go").click(); });

function refreshAll() { refreshStatus(); refreshWatch(); refreshPending(); refreshTx(); refreshScenarios(); }

(async () => {
  SETTINGS = await api("/settings");
  refreshAll();
  setInterval(refreshStatus, 5000);
  setInterval(refreshWatch, 15000);
  setInterval(refreshPending, 10000);
})();
