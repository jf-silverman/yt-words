"""
Renders data/prototypes/buy_on_pullback_results.json (+ never_trigger_model.json) into
a standalone, self-contained HTML panel for local review —
data/prototypes/buy_on_pullback_panel.html. Prototype only; not linked from the live
site yet.
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
RESULTS_PATH = ROOT / "data" / "prototypes" / "buy_on_pullback_results.json"
MODEL_PATH = ROOT / "data" / "prototypes" / "never_trigger_model.json"
OUT_PATH = ROOT / "data" / "prototypes" / "buy_on_pullback_panel.html"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Buy on Pullback — Prototype Analytics</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; max-width: 1100px; margin: 32px auto;
         padding: 0 20px; color: #24292f; background: #fff; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .subtitle {{ color: #57606a; font-size: 13px; margin: 0 0 16px; }}
  .story {{ background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 8px;
           padding: 14px 18px; margin-bottom: 20px; }}
  .story h2 {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #57606a;
              margin: 0 0 8px; font-weight: 700; }}
  .story ul {{ margin: 0; padding-left: 20px; }}
  .story li {{ font-size: 13.5px; line-height: 1.6; margin-bottom: 4px; }}
  .cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }}
  .card {{ background: #f9fafb; border: 1px solid #eaeef2; border-left: 3px solid #d0d7de;
          border-radius: 8px; padding: 12px 16px; min-width: 190px; flex: 1; }}
  .card.hero {{ background: #f0f9f2; }}
  .card h3 {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #57606a;
             margin: 0 0 8px; font-weight: 700; display: flex; align-items: center; }}
  .card h3 .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; flex-shrink: 0; }}
  .card .big {{ font-size: 22px; font-weight: 700; font-family: monospace; }}
  .card .big .unit {{ font-size: 12px; font-weight: 400; font-family: -apple-system, Arial, sans-serif; color: #57606a; margin-left: 4px; }}
  .card .sub {{ font-size: 12px; color: #57606a; margin-top: 4px; }}
  .card .triple {{ display: flex; gap: 22px; margin-top: 2px; }}
  .card .triple .stat-label {{ font-size: 10.5px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.3px; }}
  .green {{ color: #1a7f37; }}
  .red {{ color: #d03030; }}
  .bar {{ display: flex; width: 100%; height: 10px; border-radius: 5px; overflow: hidden; background: #e5e7eb; margin-top: 8px; }}
  .bar-seg {{ height: 100%; }}
  .rarity-rows {{ margin-top: 8px; }}
  .rarity-row {{ display: flex; align-items: center; gap: 8px; font-size: 11px; color: #57606a; margin-top: 4px; }}
  .rarity-row .rarity-label {{ width: 38px; font-family: monospace; }}
  .rarity-row .bar {{ margin-top: 0; flex: 1; }}
  .rarity-row .rarity-pct {{ width: 40px; text-align: right; font-family: monospace; font-weight: 700; color: #24292f; }}
  .caution-tag {{ display: inline-block; font-size: 10px; font-weight: 600; color: #9a6700;
                 background: #fff8e6; border: 1px solid #f0dca0; border-radius: 4px;
                 padding: 1px 5px; margin-left: 6px; white-space: nowrap; }}
  .section-title {{ font-size: 15px; font-weight: 700; margin: 28px 0 10px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12.5px; }}
  th, td {{ padding: 6px 8px; border-bottom: 1px solid #eaeef2; text-align: right; white-space: nowrap; }}
  th {{ text-align: right; color: #57606a; font-weight: 600; font-size: 11px;
       text-transform: uppercase; cursor: pointer; user-select: none; position: sticky; top: 0; background: #fff; }}
  th:first-child, td:first-child {{ text-align: left; }}
  td.ticker {{ font-weight: 700; font-family: monospace; }}
  td.mono {{ font-family: monospace; }}
  tr:hover {{ background: #f6f8fa; }}
  .star {{ color: #bf8700; cursor: help; font-weight: 700; }}
  .excl {{ color: #8b949e; font-style: italic; font-size: 11.5px; }}
  .training-tag {{ color: #8b949e; font-style: italic; }}
  .predicted {{ color: #0969da; font-weight: 700; }}
  .filters {{ margin: 8px 0 14px; font-size: 12.5px; display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }}
  .filters label {{ margin-right: 14px; }}
  .table-wrap {{ max-height: 640px; overflow-y: auto; overflow-x: auto; border: 1px solid #d0d7de; border-radius: 6px; }}
  .details-toggle {{ font-size: 12.5px; margin: 4px 0 10px; }}
  .details-pane {{ font-size: 12px; color: #57606a; margin: 6px 0 18px; line-height: 1.6;
                   background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 8px; padding: 14px 18px; }}
  .details-pane .star {{ margin-right: 4px; }}
</style>
</head>
<body>

<h1>Buy on Pullback — Prototype Analytics</h1>
<p class="subtitle">Local prototype, not on the live site yet. Generated {generated_at}.</p>

<div class="story">
  <h2>Top Findings</h2>
  <ul>
    <li>When a "buy on pullback" call actually pulls back, buying the dip beats buying
      immediately <strong>{beats_pct}% of the time</strong> ({b_mean}% mean return vs.
      {a_mean}%) — the wait is worth it when there's something to wait for.</li>
    <li>But <strong>{never_pct}% of these calls never pull back at all</strong> — and if
      you'd bought those anyway on the call date, you'd have averaged
      <strong>{nt_mean}%</strong> with a <strong>{nt_win}% win rate</strong>. Waiting for a
      discount that never comes is the real cost of this strategy.</li>
    <li>Those "never pulls back" stocks aren't random — they already had strong
      momentum and higher beta going in. A simple model using just beta and 30-day
      pre-call momentum predicts which calls will never trigger with
      <strong>{model_auc} AUC</strong> ({model_acc} accuracy vs. a
      {model_base_rate} base rate) — enough of an edge to flag "just buy this one now"
      candidates going forward.</li>
  </ul>
</div>

<div class="cards">
  <div class="card" style="border-left-color:#8b949e">
    <h3><span class="dot" style="background:#8b949e"></span>Total calls</h3>
    <div class="big">{total_calls}</div>
    <div class="sub">{calls_with_data} with price data</div>
  </div>
  <div class="card" style="border-left-color:#0969da">
    <h3><span class="dot" style="background:#0969da"></span>Ever pulls back within 60d</h3>
    <div class="rarity-rows">
      <div class="rarity-row"><span class="rarity-label">&ge;2%</span><div class="bar"><div class="bar-seg" style="width:{rarity_2}%;background:#0969da"></div></div><span class="rarity-pct">{rarity_2}%</span></div>
      <div class="rarity-row"><span class="rarity-label">&ge;3%</span><div class="bar"><div class="bar-seg" style="width:{rarity_3}%;background:#0969da"></div></div><span class="rarity-pct">{rarity_3}%</span></div>
      <div class="rarity-row"><span class="rarity-label">&ge;5%</span><div class="bar"><div class="bar-seg" style="width:{rarity_5}%;background:#0969da"></div></div><span class="rarity-pct">{rarity_5}%</span></div>
    </div>
  </div>
  <div class="card hero" style="border-left-color:{nt_color}">
    <h3><span class="dot" style="background:{nt_color}"></span>Never-triggered calls, bought anyway at call price</h3>
    <div class="big"><span class="{nt_cls}">{nt_mean}%</span> <span class="unit">mean</span></div>
    <div class="triple">
      <div><div class="stat-label">Median</div><div class="{nt_median_cls}" style="font-family:monospace;font-weight:700">{nt_median}%</div></div>
      <div><div class="stat-label">Win Rate</div><div style="font-family:monospace;font-weight:700">{nt_win}%</div></div>
      <div><div class="stat-label">N</div><div style="font-family:monospace;font-weight:700">{nt_n}</div></div>
    </div>
    <div class="sub" style="margin-top:8px">{never_n} of {never_of} calls ({never_pct}%) never saw a big enough
      pullback within 60 days — this is what buying them immediately anyway would have returned.</div>
  </div>
</div>

<div class="cards">
  <div class="card" style="border-left-color:{a_color}">
    <h3><span class="dot" style="background:{a_color}"></span>Strategy A — buy immediately</h3>
    <div class="big"><span class="{a_cls}">{a_mean}%</span> <span class="unit">mean</span></div>
    <div class="sub">median {a_median}% · win rate {a_win}% · n={a_n}{a_small}</div>
  </div>
  <div class="card" style="border-left-color:{b_color}">
    <h3><span class="dot" style="background:{b_color}"></span>Strategy B — buy the dip</h3>
    <div class="big"><span class="{b_cls}">{b_mean}%</span> <span class="unit">mean</span></div>
    <div class="sub">median {b_median}% · win rate {b_win}% · n={b_n}{b_small}</div>
  </div>
  <div class="card" style="border-left-color:{beats_color}">
    <h3><span class="dot" style="background:{beats_color}"></span>Strategy B beats A head-to-head</h3>
    <div class="big"><span class="{beats_cls}">{beats_pct}%</span></div>
    <div class="bar"><div class="bar-seg" style="width:{beats_pct}%;background:{beats_color}"></div></div>
    <div class="sub">{beats_count} of {beats_n} comparable calls</div>
  </div>
</div>

<div class="details-toggle">
  <label><input type="checkbox" id="detailsToggle" onchange="document.getElementById('details-pane').style.display=this.checked?'block':'none'"> Show methodology &amp; definitions</label>
</div>
<div id="details-pane" class="details-pane" style="display:none">
  <p style="margin:0 0 8px">Compares buying immediately on the call vs. waiting for a real
    pullback (volatility-scaled threshold via beta / market cap) and buying then, each held
    for its own 60 days.</p>
  <div><span class="star">*</span> = Cramer made another call on this ticker within 60 days of the
    buy-on-pullback call (hover the asterisk for details).</div>
  <div><span class="excl">excluded</span> = a real pullback occurred, but Cramer downgraded to
    hold/sell <em>before</em> the dip was reached, so buying it would contradict his own updated
    view — dropped from the Strategy B averages above.</div>
  <div><span class="training-tag">used for training</span> = this call was part of the data used
    to fit the never-trigger prediction model; <span class="predicted">predicted</span> = a call
    added after the model was trained, scored live using its beta and pre-call momentum.</div>
</div>

<div class="section-title">Per-call detail</div>
<div class="filters">
  <label>Filter by note:
    <select id="noteFilter" onchange="renderTable()">
      <option value="">All</option>
    </select>
  </label>
</div>
<div class="table-wrap">
<table id="callsTable">
  <thead>
    <tr>
      <th onclick="sortBy('ticker')">Ticker</th>
      <th onclick="sortBy('call_date')">Call Date</th>
      <th onclick="sortBy('call_price')">Call Px</th>
      <th onclick="sortBy('threshold_pct')">Threshold</th>
      <th onclick="sortBy('max_drawdown_pct')">Max Drawdown</th>
      <th onclick="sortBy('dip_date')">Dip Date</th>
      <th onclick="sortBy('strategy_a_return_pct')">A Return</th>
      <th onclick="sortBy('strategy_b_return_pct')">B Return</th>
      <th onclick="sortBy('ntpSort')">Predict Never-Trigger</th>
      <th onclick="sortBy('noteLabel')">Note</th>
    </tr>
  </thead>
  <tbody></tbody>
</table>
</div>

<script>
const DATA = {calls_json};

function noteLabelFor(r) {{
  if (r.dip_excluded_reason) return r.dip_excluded_reason;
  if (!r.dip_triggered) return 'never triggered';
  if (r.strategy_b_note) return r.strategy_b_note;
  return '(comparable)';
}}
DATA.forEach(r => r.noteLabel = noteLabelFor(r));

function ntpSortFor(r) {{
  const p = r.never_trigger_prediction;
  if (!p) return -3000;
  if (p.status === 'predicted') return p.prob_never_trigger_pct;
  if (p.status === 'training') return -1000;
  return -2000;
}}
DATA.forEach(r => r.ntpSort = ntpSortFor(r));

const noteSelect = document.getElementById('noteFilter');
[...new Set(DATA.map(r => r.noteLabel))].sort().forEach(label => {{
  const opt = document.createElement('option');
  opt.value = label;
  opt.textContent = label;
  noteSelect.appendChild(opt);
}});

let sortKey = 'call_date';
let sortDir = -1;

function sortBy(key) {{
  if (sortKey === key) sortDir *= -1; else {{ sortKey = key; sortDir = -1; }}
  renderTable();
}}

function fmtPct(v) {{
  if (v === null || v === undefined) return '—';
  const cls = v >= 0 ? 'green' : 'red';
  return `<span class="${{cls}}">${{v.toFixed(2)}}%</span>`;
}}

function fmtPrediction(r) {{
  const p = r.never_trigger_prediction;
  if (!p) return '—';
  if (p.status === 'training') return '<span class="training-tag">used for training</span>';
  if (p.status === 'predicted') return `<span class="predicted">${{p.prob_never_trigger_pct}}% never-trigger</span>`;
  if (p.status === 'insufficient_data') return '<span class="excl">insufficient data</span>';
  return '<span class="excl">model not trained</span>';
}}

function renderTable() {{
  const noteFilter = noteSelect.value;
  let rows = DATA.slice();
  if (noteFilter) rows = rows.filter(r => r.noteLabel === noteFilter);

  rows.sort((a, b) => {{
    let av = a[sortKey], bv = b[sortKey];
    if (av === null || av === undefined) av = -Infinity;
    if (bv === null || bv === undefined) bv = -Infinity;
    if (typeof av === 'string' && typeof bv === 'string') {{
      return av.localeCompare(bv) * sortDir;
    }}
    if (av < bv) return -1 * sortDir;
    if (av > bv) return 1 * sortDir;
    return 0;
  }});

  const tbody = document.querySelector('#callsTable tbody');
  tbody.innerHTML = rows.map(r => {{
    const star = r.superseded_within_60d
      ? `<span class="star" title="${{r.other_calls_within_60d.map(o => o.date + ': ' + o.sentiment).join('\\n')}}">*</span>`
      : '';
    const noteCls = r.noteLabel === '(comparable)' ? '' : 'excl';
    return `<tr>
      <td class="ticker">${{r.ticker}}${{star}}</td>
      <td class="mono">${{r.call_date}}</td>
      <td class="mono">$${{r.call_price.toFixed(2)}}</td>
      <td class="mono">${{r.threshold_pct}}% (${{r.threshold_source}})</td>
      <td class="mono">${{r.max_drawdown_pct.toFixed(2)}}%</td>
      <td class="mono">${{r.dip_date || '—'}}</td>
      <td>${{fmtPct(r.strategy_a_return_pct)}}</td>
      <td>${{fmtPct(r.strategy_b_return_pct)}}</td>
      <td>${{fmtPrediction(r)}}</td>
      <td class="${{noteCls}}">${{r.noteLabel}}</td>
    </tr>`;
  }}).join('');
}}

renderTable();
</script>

</body>
</html>
"""


GREEN = "#1a7f37"
RED = "#d03030"


def _pct_color(v):
    return GREEN if v >= 0 else RED


def _pct_cls(v):
    return "green" if v >= 0 else "red"


def _small_sample_badge(small):
    return ' <span class="caution-tag">small sample</span>' if small else ""


def render():
    payload = json.loads(RESULTS_PATH.read_text())
    s = payload["summary"]
    a = s["strategy_a_buy_immediately"]
    b = s["strategy_b_buy_the_dip"]
    beats_pct = s["b_beats_a"]["pct"] or 0
    nt = s["never_triggered"]["strategy_a_if_bought_anyway"]
    never = s["never_triggered"]

    model = json.loads(MODEL_PATH.read_text()) if MODEL_PATH.exists() else None
    model_auc = f"{model['cv_auc']:.2f}" if model else "n/a"
    model_acc = f"{model['cv_accuracy'] * 100:.0f}%" if model else "n/a"
    model_base_rate = f"{(1 - never['n'] / s['calls_with_price_data']) * 100:.0f}%" if model else "n/a"

    never_of = never["n"] + s["b_beats_a"]["n"] + s["triggered_but_insufficient_b_data"] + s["excluded_downgraded_before_dip"]

    html = HTML_TEMPLATE.format(
        generated_at=payload["generated_at"],
        total_calls=s["total_buy_on_pullback_calls"],
        calls_with_data=s["calls_with_price_data"],
        rarity_2=s["rarity"][">= 2% drawdown within 60d"]["pct_of_evaluable"],
        rarity_3=s["rarity"][">= 3% drawdown within 60d"]["pct_of_evaluable"],
        rarity_5=s["rarity"][">= 5% drawdown within 60d"]["pct_of_evaluable"],
        a_mean=a["mean_pct"], a_median=a["median_pct"], a_win=a["win_rate_pct"], a_n=a["n"],
        a_color=_pct_color(a["mean_pct"]), a_cls=_pct_cls(a["mean_pct"]),
        a_small=_small_sample_badge(a["small_sample"]),
        b_mean=b["mean_pct"], b_median=b["median_pct"], b_win=b["win_rate_pct"], b_n=b["n"],
        b_color=_pct_color(b["mean_pct"]), b_cls=_pct_cls(b["mean_pct"]),
        b_small=_small_sample_badge(b["small_sample"]),
        beats_pct=beats_pct, beats_count=s["b_beats_a"]["count"], beats_n=s["b_beats_a"]["n"],
        beats_color=GREEN if beats_pct >= 50 else RED, beats_cls="green" if beats_pct >= 50 else "red",
        never_n=never["n"], never_of=never_of, never_pct=never["pct_of_full_a_window_calls"],
        nt_mean=nt["mean_pct"], nt_median=nt["median_pct"], nt_win=nt["win_rate_pct"], nt_n=nt["n"],
        nt_color=_pct_color(nt["mean_pct"]), nt_cls=_pct_cls(nt["mean_pct"]), nt_median_cls=_pct_cls(nt["median_pct"]),
        model_auc=model_auc, model_acc=model_acc, model_base_rate=model_base_rate,
        calls_json=json.dumps(payload["calls"]),
    )
    OUT_PATH.write_text(html)
    print(f"Panel written to {OUT_PATH}")


if __name__ == "__main__":
    render()
