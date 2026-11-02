/* ================= gold panel ================= */
var GOLD = DATA.gold || null;
var goldState = { live:null, liveTh:null, lineW:0, fcW:0 };
function fmtN(v){ if(v==null || v==='' || isNaN(Number(v))) return '—'; return Math.round(Number(v)).toLocaleString('en-US'); }
function trendOf(v){ var n = Number(v); return n>0?'up':n<0?'down':'flat'; }
function signPct(v){ if(v==null || v==='') return '—'; var n = Number(v); return (n>0?'+':n<0?'−':'') + Math.abs(n).toLocaleString('en-US', {maximumFractionDigits:1}) + '%'; }
function signN(v, unit){ if(v==null || v==='') return '—'; var n = Number(v); return (n>0?'+':n<0?'−':'') + fmtN(Math.abs(n)) + (unit||''); }
function thaiDateTime(iso){
  var t = Date.parse(iso||''); if(isNaN(t)) return thaiDate(iso);
  var d = new Date(t);
  return d.getDate() + ' ' + TH_MONTHS[d.getMonth()] + ' ' + (d.getFullYear()+543) + ' ' + ('0'+d.getHours()).slice(-2) + ':' + ('0'+d.getMinutes()).slice(-2) + ' น.';
}
function svgEl(tag, attrs, text){
  var e = document.createElementNS('http://www.w3.org/2000/svg', tag);
  if(attrs) for(var k in attrs){ if(attrs[k]!=null) e.setAttribute(k, attrs[k]); }
  if(text!=null) e.textContent = text;
  return e;
}
function niceTicks(lo, hi, step){ var out = [], t = Math.ceil(lo/step)*step; while(t<=hi){ out.push(t); t += step; } return out; }
function liveNum(it){ if(!it || it.value==null) return null; var v = parseFloat(String(it.value).replace(/[^0-9.\-]/g, '')); return isNaN(v) ? null : v; }
function goldHeadlineValue(){ var v = liveNum(goldState.live); return v!=null ? v : (GOLD ? GOLD.spot_now : null); }

/* --- 2569 line chart: month-end closes, peak marker, support + MA200 reference lines --- */
function drawGoldLine(wrap, w){
  var g = GOLD, pts = g.series_2026.points, pk = g.series_2026.peak_marker, n = pts.length;
  wrap.innerHTML = '';
  var H = 236, M = {l:46, r:14, t:22, b:28}, iw = w - M.l - M.r, ih = H - M.t - M.b;
  var vals = pts.map(function(p){ return p[1]; }).concat([pk.value, g.levels.chart_support, g.levels.ma200]);
  var lo = Math.floor((Math.min.apply(null, vals) - 120)/100)*100, hi = Math.ceil((Math.max.apply(null, vals) + 80)/100)*100;
  var step = iw/(n-1);
  function X(i){ return M.l + i*step; }
  function Y(v){ return M.t + (hi - v)/(hi - lo)*ih; }
  var svg = svgEl('svg', {viewBox:'0 0 '+w+' '+H, width:w, height:H, role:'img', 'aria-label':'กราฟราคาทองโลกปี 2569 รายเดือน'});
  niceTicks(lo, hi, 500).forEach(function(t){
    svg.appendChild(svgEl('line', {class:'grid', x1:M.l, x2:w-M.r, y1:Y(t), y2:Y(t)}));
    svg.appendChild(svgEl('text', {class:'ax', x:M.l-6, y:Y(t)+4, 'text-anchor':'end'}, fmtN(t)));
  });
  svg.appendChild(svgEl('text', {class:'axm', x:M.l-6, y:M.t-9, 'text-anchor':'end'}, '$/ออนซ์'));
  var every = step < 30 ? 2 : 1;
  pts.forEach(function(p, i){ if(i%every===0 || i===n-1) svg.appendChild(svgEl('text', {class:'axm', x:X(i), y:H-8, 'text-anchor':'middle'}, p[0])); });
  var ys = Y(g.levels.chart_support), ym = Y(g.levels.ma200);
  svg.appendChild(svgEl('line', {class:'ref', x1:M.l, x2:w-M.r, y1:ys, y2:ys}));
  svg.appendChild(svgEl('text', {class:'reft', x:M.l+4, y:ys-4}, 'แนวรับ ' + fmtN(g.levels.chart_support)));
  svg.appendChild(svgEl('line', {class:'ref', x1:M.l, x2:w-M.r, y1:ym, y2:ym}));
  svg.appendChild(svgEl('text', {class:'reft', x:w-M.r, y:ym-4, 'text-anchor':'end'}, 'MA200 ' + fmtN(g.levels.ma200)));
  var d = pts.map(function(p, i){ return (i?'L':'M') + X(i).toFixed(1) + ' ' + Y(p[1]).toFixed(1); }).join(' ');
  svg.appendChild(svgEl('path', {class:'area', d: d + ' L' + X(n-1).toFixed(1) + ' ' + (M.t+ih) + ' L' + X(0).toFixed(1) + ' ' + (M.t+ih) + ' Z'}));
  svg.appendChild(svgEl('path', {class:'ln', d:d}));
  var pi = -1; pts.forEach(function(p, i){ if(p[0]===pk.label_th) pi = i; });
  if(pi>=0){
    svg.appendChild(svgEl('line', {class:'lead', x1:X(pi), x2:X(pi), y1:Y(pk.value)+5, y2:Y(pts[pi][1])-4}));
    svg.appendChild(svgEl('circle', {class:'mk peak', cx:X(pi), cy:Y(pk.value), r:4.5}));
    svg.appendChild(svgEl('text', {class:'lab', x:X(pi)+9, y:Y(pk.value)+1}, 'สถิติ $' + fmtN(pk.value)));
    svg.appendChild(svgEl('text', {class:'lab2', x:X(pi)+9, y:Y(pk.value)+13}, thaiDate(pk.date)));
  }
  var last = pts[n-1];
  svg.appendChild(svgEl('circle', {class:'mk', cx:X(n-1), cy:Y(last[1]), r:5}));
  var cur = svgEl('text', {class:'lab', x:X(n-1)-9, y:Y(last[1])+22, 'text-anchor':'end'}, '$' + fmtN(last[1]));
  cur.insertBefore(svgEl('tspan', {class:'lab2'}, 'ปิดศุกร์ '), cur.firstChild);
  svg.appendChild(cur);
  var cross = svgEl('line', {class:'cross', x1:0, x2:0, y1:M.t, y2:M.t+ih, visibility:'hidden'});
  var hov = svgEl('circle', {class:'hov', r:5, visibility:'hidden'});
  var hit = svgEl('rect', {x:M.l-step/2, y:0, width:iw+step, height:H, fill:'transparent'});
  svg.appendChild(cross); svg.appendChild(hov); svg.appendChild(hit);
  wrap.appendChild(svg);
  var tip = h('div', {class:'chart-tip', hidden:''}); wrap.appendChild(tip);
  function show(ev){
    var r = svg.getBoundingClientRect(), sc = r.width / w;
    var i = Math.max(0, Math.min(n-1, Math.round(((ev.clientX - r.left)/sc - M.l)/step)));
    cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('visibility', 'visible');
    hov.setAttribute('cx', X(i)); hov.setAttribute('cy', Y(pts[i][1])); hov.setAttribute('visibility', 'visible');
    tip.innerHTML = ''; tip.appendChild(h('span', {text:(i===0 ? pts[i][0] : pts[i][0] + ' 2569') + ' · '})); tip.appendChild(h('b', {text:'$' + fmtN(pts[i][1])}));
    tip.hidden = false;
    var wr = wrap.getBoundingClientRect(), tw = tip.offsetWidth;
    var left = (r.left - wr.left) + X(i)*sc + (i > n/2 ? -tw-12 : 12);
    tip.style.left = Math.max(4, Math.min(wr.width - tw - 4, left)) + 'px';
    tip.style.top = Math.max(4, (r.top - wr.top) + Y(pts[i][1])*sc - 34) + 'px';
  }
  function hide(){ cross.setAttribute('visibility', 'hidden'); hov.setAttribute('visibility', 'hidden'); tip.hidden = true; }
  svg.addEventListener('pointermove', show); svg.addEventListener('pointerdown', show);
  svg.addEventListener('pointerleave', hide); svg.addEventListener('pointercancel', hide);
}

/* --- analyst targets: dumbbell end-2569 -> end-2570, one hue + neutral --- */
function drawGoldForecast(wrap, w){
  var g = GOLD, rows = g.forecasts.items, spot = goldHeadlineValue();
  wrap.innerHTML = '';
  var rowH = 44, M = {l:8, r:46, t:26, b:22}, H = M.t + rows.length*rowH + M.b, iw = w - M.l - M.r;
  var vals = [spot]; rows.forEach(function(r){ if(r.end_2026!=null) vals.push(r.end_2026); if(r.end_2027!=null) vals.push(r.end_2027); });
  var lo = Math.floor((Math.min.apply(null, vals) - 250)/100)*100, hi = Math.ceil((Math.max.apply(null, vals) + 100)/100)*100;
  function X(v){ return M.l + (v - lo)/(hi - lo)*iw; }
  var svg = svgEl('svg', {viewBox:'0 0 '+w+' '+H, width:w, height:H, role:'img', 'aria-label':'เป้าหมายราคาทองของนักวิเคราะห์ สิ้นปี 2569 และ 2570'});
  niceTicks(lo, hi, 500).forEach(function(t){
    svg.appendChild(svgEl('line', {class:'grid', x1:X(t), x2:X(t), y1:M.t-6, y2:H-M.b}));
    svg.appendChild(svgEl('text', {class:'ax', x:X(t), y:M.t-11, 'text-anchor':'middle'}, fmtN(t)));
  });
  if(spot!=null){
    svg.appendChild(svgEl('line', {class:'db-now', x1:X(spot), x2:X(spot), y1:M.t-6, y2:H-M.b}));
    svg.appendChild(svgEl('text', {class:'reft', x:X(spot)+4, y:H-6}, 'ตอนนี้ $' + fmtN(spot)));
  }
  rows.forEach(function(r, i){
    var y = M.t + i*rowH, yd = y + 30;
    var nm = svgEl('text', {class:'nm', x:M.l, y:y+13}, r.name);
    if(r.note_th){ nm.appendChild(svgEl('tspan', {class:'nm2', dx:6}, '· ' + r.note_th)); }
    svg.appendChild(nm);
    var a = r.end_2026, b = r.end_2027;
    if(a!=null && b!=null) svg.appendChild(svgEl('line', {class:'db-line', x1:X(a), x2:X(b), y1:yd, y2:yd}));
    if(a!=null){
      svg.appendChild(svgEl('circle', {class:'mk peak', cx:X(a), cy:yd, r:4.5}));
      svg.appendChild(svgEl('text', {class:'lab', x:X(a)-9, y:yd+4, 'text-anchor':'end'}, fmtN(a)));
    }
    if(b!=null){
      svg.appendChild(svgEl('circle', {class:'mk', cx:X(b), cy:yd, r:5}));
      svg.appendChild(svgEl('text', {class:'lab', x:X(b)+9, y:yd+4}, fmtN(b)));
    } else if(a!=null){
      svg.appendChild(svgEl('text', {class:'lab2', x:X(a)+9, y:yd+4}, 'ไม่ระบุปี 2570'));
    }
  });
  wrap.appendChild(svg);
}

function goldLayout(){
  if(!GOLD) return;
  var a = $('gold-chart'), b = $('gold-fc');
  if(a && a.clientWidth > 40){ var wa = a.clientWidth - 16; if(wa !== goldState.lineW){ goldState.lineW = wa; drawGoldLine(a, wa); } }
  if(b && b.clientWidth > 40){ var wb = b.clientWidth - 16; if(wb !== goldState.fcW){ goldState.fcW = wb; drawGoldForecast(b, wb); } }
}

(function renderGold(){
  var v = $('view-gold');
  if(!GOLD){ v.appendChild(h('p', {text:'ไม่มีข้อมูลทองคำในชุดข้อมูลนี้', style:'color:var(--muted)'})); return; }
  var g = GOLD, th = g.thai || {}, lv = g.levels || {}, se = g.sentiment || null;
  v.appendChild(h('div', {class:'gold-head'}, [
    h('h2', {text:'ทองคำ'}),
    h('div', {class:'asof'}, [h('div', {text:g.as_of_caption_th || ('ราคาโลก ณ ' + thaiDateTime(g.as_of))}), h('div', {text:'ดอลลาร์สหรัฐ/ทรอยออนซ์'})])
  ]));
  function liveTag(){ return h('span', {class:'live-tag', hidden:''}, [h('span', {class:'sdot fresh', 'data-dot':''}), 'สด']); }
  var tiles = h('div', {class:'tiles'}, [
    h('div', {class:'tile gold-main', id:'gold-tile-main'}, [
      h('div', {class:'lbl'}, ['ราคาทองโลก (spot)', liveTag()]),
      h('div', {class:'val', text:'$' + fmtN(g.spot_now)}),
      h('div', {class:'delta'}, [h('span', {class:'tr ' + trendOf(g.change_day_pct), text:TREND_GLYPH[trendOf(g.change_day_pct)]}), h('span', {text:signPct(g.change_day_pct) + ' วันนี้'})]),
      h('div', {class:'src'}, [h('span', {text:'ณ ' + thaiDateTime(g.as_of)}), h('span', {text:g.spot_note_th || ''})])
    ]),
    h('div', {class:'tile'}, [
      h('div', {class:'lbl', text:'เปลี่ยนแปลงวันนี้'}),
      h('div', {class:'val', text:signPct(g.change_day_pct)}),
      h('div', {class:'delta'}, [h('span', {class:'tr ' + trendOf(g.change_week_pct), text:TREND_GLYPH[trendOf(g.change_week_pct)]}), h('span', {text:'สัปดาห์ ' + signPct(g.change_week_pct) + ' · ต.ค. ' + signPct(g.change_oct_pct)})]),
      h('div', {class:'src'}, [h('span', {text:'เปิดปี $' + fmtN(g.year_open) + ' · ต่ำสุดปี $' + fmtN(g.year_low) + ' (' + (g.year_low_note_th||'') + ')'})])
    ]),
    h('div', {class:'tile'}, [
      h('div', {class:'lbl', text:'จากจุดสูงสุดตลอดกาล'}),
      h('div', {class:'val', text:signPct(g.from_peak_pct)}),
      h('div', {class:'delta'}, [h('span', {class:'tr down', text:TREND_GLYPH.down}), h('span', {text:'สถิติ $' + fmtN(g.peak)})]),
      h('div', {class:'src'}, [h('span', {text:thaiDate(g.peak_date)})])
    ]),
    h('div', {class:'tile gold-main', id:'gold-tile-th'}, [
      h('div', {class:'lbl'}, [(th.label_th||'ทองไทย') + ' ขายออก', liveTag()]),
      h('div', {class:'val', text:fmtN(th.sell)}),
      h('div', {class:'delta'}, [h('span', {class:'tr down', text:TREND_GLYPH.down}), h('span', {text:'รับซื้อ ' + fmtN(th.buy) + ' บาท · ' + signN(th.two_day_change_baht) + ' จากปิดศุกร์'})]),
      h('div', {class:'src'}, [h('span', {text:thaiDateTime(th.as_of)}), h('span', {text:th.source_th||''})])
    ])
  ]);
  v.appendChild(tiles);

  v.appendChild(h('h3', {class:'sec-title', text:'ราคาทองโลกปี 2569'}));
  v.appendChild(h('div', {class:'chart-wrap', id:'gold-chart-wrap'}, [
    h('div', {class:'chart-title'}, [h('span', {text:'ราคาปิดปลายเดือน (ดอลลาร์/ออนซ์)'}), h('span', {class:'note', text:g.series_2026.note_th||''})]),
    h('div', {id:'gold-chart'}),
    h('div', {class:'chart-legend'}, [
      h('span', null, [h('i'), 'ราคาปิดเดือน']),
      h('span', null, [h('i', {class:'dot'}), 'จุดสูงสุดระหว่างวัน']),
      h('span', null, [h('i', {class:'dash'}), 'แนวรับ ' + fmtN(lv.chart_support) + ' / MA200 ' + fmtN(lv.ma200)])
    ])
  ]));

  v.appendChild(h('h3', {class:'sec-title', text:'เป้าหมายของนักวิเคราะห์'}));
  v.appendChild(h('div', {class:'chart-wrap'}, [
    h('div', {class:'chart-title'}, [h('span', {text:'เป้าหมายราคาสิ้นปี (ดอลลาร์/ออนซ์)'}), h('span', {class:'note', text:g.forecasts.note_th||''})]),
    h('div', {id:'gold-fc'}),
    h('div', {class:'chart-legend'}, [
      h('span', null, [h('i', {class:'dot'}), 'สิ้นปี 2569']),
      h('span', null, [h('i', {class:'dot fill'}), 'สิ้นปี 2570']),
      h('span', null, [h('i', {class:'dash'}), 'ราคาตอนนี้'])
    ])
  ]));

  function fold(title, open, body){
    var dt = h('details', {class:'fold'}, [h('summary', {text:title}), h('div', {class:'fold-body'}, body)]);
    if(open) dt.setAttribute('open', '');
    return dt;
  }
  function ul(items, cls){ var u = h('ul', {class:cls||'points'}); (items||[]).forEach(function(p){ u.appendChild(h('li', {text:p})); }); return u; }

  v.appendChild(h('h3', {class:'sec-title', text:'เจาะลึก'}));
  v.appendChild(fold((g.drivers_th && g.drivers_th.title_th) || 'ทำไมลง', true, [ul(g.drivers_th && g.drivers_th.points)]));
  v.appendChild(fold((g.supports_th && g.supports_th.title_th) || 'แรงหนุน', false, [ul(g.supports_th && g.supports_th.points)]));

  if(se){
    var sb = h('div', {class:'sent'});
    [['มองลง', se.bearish, 'bad'], ['เป็นกลาง', se.neutral, 'muted'], ['มองขึ้น', se.bullish, 'good']].forEach(function(s){
      if(s[1]==null) return;
      sb.appendChild(h('div', {class:'sent-row'}, [h('span', {class:'sent-l', text:s[0]}), h('span', {class:'sent-bar'}, [h('span', {class:'sent-fill ' + s[2], style:'width:' + Math.max(0, Math.min(100, s[1])) + '%'})]), h('span', {class:'sent-v', text:s[1] + '%'})]));
    });
    v.appendChild(fold(se.title_th || 'ความเห็นตลาด', false, [
      se.survey_th ? h('p', {text:se.survey_th}) : null,
      sb,
      h('h3', {class:'sec-title', text:'เป้าฝั่งมองลง'}), ul(se.bear_targets_th, 'risks down'),
      h('h3', {class:'sec-title', text:'เสียงแย้ง'}), ul(se.counter_th, 'risks up')
    ]));
  }

  var tbl = h('table', {class:'lv-table'}, [h('thead', null, [h('tr', null, [h('th', {text:'ระดับ ($)'}), h('th', {text:'บทบาท'}), h('th', {text:'หมายเหตุ'})])])]);
  var tb = h('tbody');
  (lv.support||[]).forEach(function(s){
    var testing = s.role==='support' && g.spot_now <= s.hi + 40 && g.spot_now >= s.lo - 40;
    tb.appendChild(h('tr', null, [
      h('td', {class:'n', text:s.range_th}),
      h('td', null, [h('span', {class:'lv-tag ' + (s.role==='resistance' ? 'res' : testing ? 'now' : 'sup'), text:s.role==='resistance' ? 'แนวต้าน' : testing ? 'แนวรับ · กำลังทดสอบ' : 'แนวรับ'})]),
      h('td', {text:s.note_th||''})
    ]));
  });
  if(lv.ma200) tb.appendChild(h('tr', null, [h('td', {class:'n', text:fmtN(lv.ma200)}), h('td', null, [h('span', {class:'lv-tag', text:'MA200'})]), h('td', {text:'ราคาต่ำกว่าเส้นค่าเฉลี่ย 200 วันราว ' + Math.abs(Math.round((g.spot_now/lv.ma200 - 1)*100)) + '%'})]));
  if(lv.rsi_daily!=null) tb.appendChild(h('tr', null, [h('td', {class:'n', text:String(lv.rsi_daily)}), h('td', null, [h('span', {class:'lv-tag', text:'RSI รายวัน'})]), h('td', {text:lv.rsi_daily < 30 ? 'อยู่ในเขตขายมากเกินไป (ต่ำกว่า 30)' : 'ใกล้เขตขายมากเกินไป (ต่ำกว่า 30)'})]));
  tbl.appendChild(tb);
  v.appendChild(fold('ระดับเทคนิค', false, [h('div', {class:'lv-wrap'}, [tbl])]));

  v.appendChild(fold('ทองไทย (' + (th.label_th||'96.5%') + ')', false, [
    h('div', {class:'kv', style:'margin-top:0'}, [
      kv('ทองแท่ง ขายออก', fmtN(th.sell) + ' บาท'), kv('ทองแท่ง รับซื้อ', fmtN(th.buy) + ' บาท'),
      kv('ทองรูปพรรณ ขายออก', fmtN(th.ornament_sell) + ' บาท'), kv('ปิดศุกร์ 30 ต.ค.', fmtN(th.friday_sell) + ' บาท'),
      kv('ปรับเสาร์ 31 ต.ค.', signN(th.sat_change_baht, ' บาท')), kv('ปรับอาทิตย์ 1 พ.ย.', signN(th.sun_change_baht, ' บาท')),
      kv('เปิดปี 2569', fmtN(th.year_open) + ' บาท'), kv('สถิติสูงสุด (' + (th.record_note_th||'') + ')', fmtN(th.record) + ' บาท'),
      kv('ต่ำสุดของปี', fmtN(th.year_low) + ' บาท'), kv('เปลี่ยนแปลงเดือน ต.ค. (รวมเสาร์)', signN(th.oct_change_baht, ' บาท')),
      kv('ตั้งแต่ต้นปี', signPct(th.ytd_pct)), kv('อัปเดต', thaiDateTime(th.as_of) + ' · ' + (th.source_th||''))
    ]),
    th.analyst_range_th ? h('p', {text:th.analyst_range_th}) : null,
    th.note_th ? h('p', {text:th.note_th}) : null
  ]));

  var ol = g.outlook_th || {};
  var sc = h('div', {class:'scen'});
  (ol.scenarios||[]).forEach(function(s){ sc.appendChild(h('div', null, [h('div', {class:'k', text:s.k}), h('div', {text:s.text})])); });
  var cal = ol.calendar_th;
  v.appendChild(fold('แนวโน้ม', false, [
    sc,
    cal ? h('h3', {class:'sec-title', text:cal.title_th || 'ปฏิทินสัปดาห์หน้า'}) : null, cal ? ul(cal.items, 'points') : null,
    h('h3', {class:'sec-title', text:'ปัจจัยหนุนให้ขึ้น'}), ul(ol.risks_up, 'risks up'),
    h('h3', {class:'sec-title', text:'ปัจจัยกดดันให้ลง'}), ul(ol.risks_down, 'risks down')
  ]));

  v.appendChild(h('div', {class:'gold-foot'}, [
    h('div', null, [h('b', {text:g.disclaimer_th||''})]),
    h('div', {text:'ราคาโลก ณ ' + thaiDateTime(g.as_of) + ' · ทองไทย ณ ' + thaiDateTime(th.as_of) + (g.updated_th ? ' · ' + g.updated_th : '') + ' · ชุดข้อมูลรายเดือนเป็นค่าโดยประมาณ'}),
    h('div', {text:'แหล่งที่มา: ' + (g.sources||[]).join(' · ')})
  ]));

  if(window.ResizeObserver){ new ResizeObserver(function(){ goldLayout(); }).observe($('panel-body')); }
  else window.addEventListener('resize', goldLayout);
})();

/* live override of the two headline tiles from live/market: key gold|xau ($/oz) and gold_th (baht) */
function goldLiveTile(tile, it, prefix, embedded){
  if(!tile) return false;
  var val = tile.querySelector('.val'), tr = tile.querySelector('.delta .tr'), chg = tile.querySelector('.delta span:last-child'), src = tile.querySelector('.src'), tag = tile.querySelector('.live-tag');
  var before = val.textContent;
  if(it){
    var v = liveNum(it), trend = ['up','down','flat'].indexOf(it.trend) >= 0 ? it.trend : 'flat';
    val.textContent = v!=null ? prefix + fmtN(v) : String(it.value);
    tr.textContent = TREND_GLYPH[trend]; tr.className = 'tr ' + trend;
    chg.textContent = it.change_th ? String(it.change_th) : '';
    src.innerHTML = ''; src.appendChild(h('span', {text:'สด · ' + (it.as_of ? relTh(it.as_of) : relTh(liveStamp()))}));
    if(it.source) src.appendChild(h('a', {href:String(it.source), target:'_blank', rel:'noopener noreferrer', text:domain(String(it.source))}));
    tag.hidden = false; var dot = tag.querySelector('.sdot'); dot.setAttribute('data-dot', it.as_of || liveStamp() || ''); setDot(dot, it.as_of || liveStamp());
  } else {
    val.textContent = embedded.val; tr.textContent = TREND_GLYPH[embedded.trend]; tr.className = 'tr ' + embedded.trend; chg.textContent = embedded.chg;
    src.innerHTML = ''; embedded.src.forEach(function(s){ src.appendChild(h('span', {text:s})); });
    tag.hidden = true;
  }
  return before !== val.textContent;
}
function goldLive(items){
  if(!GOLD) return;
  var it = null, itTh = null;
  (items||[]).forEach(function(x){ if(!x || typeof x !== 'object') return; if(!it && (x.key==='gold' || x.key==='xau')) it = x; if(!itTh && x.key==='gold_th') itTh = x; });
  var prevV = liveNum(goldState.live), had = !!(goldState.live || goldState.liveTh);
  goldState.live = (it && !live.offline) ? it : null; goldState.liveTh = (itTh && !live.offline) ? itTh : null;
  var th = GOLD.thai || {};
  var c1 = goldLiveTile($('gold-tile-main'), goldState.live, '$', {val:'$' + fmtN(GOLD.spot_now), trend:trendOf(GOLD.change_day_pct), chg:signPct(GOLD.change_day_pct) + ' วันนี้', src:['ณ ' + thaiDateTime(GOLD.as_of), GOLD.spot_note_th || '']});
  var c2 = goldLiveTile($('gold-tile-th'), goldState.liveTh, '', {val:fmtN(th.sell), trend:trendOf(th.two_day_change_baht), chg:'รับซื้อ ' + fmtN(th.buy) + ' บาท · ' + signN(th.two_day_change_baht) + ' จากปิดศุกร์', src:[thaiDateTime(th.as_of), th.source_th || '']});
  if(had || goldState.live || goldState.liveTh){ if(c1) flash($('gold-tile-main')); if(c2) flash($('gold-tile-th')); }
  if(prevV !== liveNum(goldState.live)){ goldState.fcW = 0; goldLayout(); }
}
