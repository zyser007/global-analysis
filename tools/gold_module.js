/* ================= gold panel ================= */
/* data/gold.json is embedded at build time (analysis + values of its own date). The live layer feeds
   market.json (gold, gold_th) and gold_history.json in here; a live item replaces the embedded value only
   when its as_of is newer. Narrative analysis cannot be live and carries an "บทวิเคราะห์ ณ <date>" label. */
var GOLD = DATA.gold || null;
var goldState = { live:null, liveTh:null, hist:null, lineW:0, fcW:0, lineSig:'', fcSig:'', painted:false, vm:null };
var GOLD_STALE_H = 10;            /* trading hours without a newer quote -> "ข้อมูลเก่า" */
var GOLD_REF_MAX_MS = 4*86400000; /* a previous-day reference older than this is not used for the day change */
function fmtN(v){ if(v==null || v==='' || isNaN(Number(v))) return '—'; return Math.round(Number(v)).toLocaleString('en-US'); }
function trendOf(v){ var n = Number(v); return n>0?'up':n<0?'down':'flat'; }
function signPct(v){ if(v==null || v==='' || isNaN(Number(v))) return '—'; var n = Number(v); if(Math.abs(n) < 0.05) n = 0; return (n>0?'+':n<0?'−':'') + Math.abs(n).toLocaleString('en-US', {minimumFractionDigits:1, maximumFractionDigits:1}) + '%'; }
function signN(v, unit){ if(v==null || v==='') return '—'; var n = Number(v); return (n>0?'+':n<0?'−':'') + fmtN(Math.abs(n)) + (unit||''); }
/* Bangkok wall clock (UTC+7), Buddhist-era year */
function thaiDateTime(iso){
  var t = Date.parse(iso||''); if(isNaN(t)) return thaiDate(iso);
  var d = new Date(t + 7*3600000);
  return d.getUTCDate() + ' ' + TH_MONTHS[d.getUTCMonth()] + ' ' + (d.getUTCFullYear()+543) + ' ' + ('0'+d.getUTCHours()).slice(-2) + ':' + ('0'+d.getUTCMinutes()).slice(-2) + ' น.';
}
function bkkDay(t){ return new Date(t + 7*3600000).toISOString().slice(0, 10); }
function thaiDayShort(t){ var d = new Date(t + 7*3600000); return d.getUTCDate() + ' ' + TH_MONTHS[d.getUTCMonth()]; }
function svgEl(tag, attrs, text){
  var e = document.createElementNS('http://www.w3.org/2000/svg', tag);
  if(attrs) for(var k in attrs){ if(attrs[k]!=null) e.setAttribute(k, attrs[k]); }
  if(text!=null) e.textContent = text;
  return e;
}
function niceTicks(lo, hi, step){ var out = [], t = Math.ceil(lo/step)*step; while(t<=hi){ out.push(t); t += step; } return out; }
function liveNum(it){ if(!it || it.value==null) return null; var v = parseFloat(String(it.value).replace(/[^0-9.\-]/g, '')); return isNaN(v) ? null : v; }

/* --- live vs embedded --- */
/* spot trades ~23 h Mon-Fri (closed Fri 22:00 - Sun 22:00 UTC); the Thai association announces Mon-Fri 09:00-17:30 Bangkok.
   A quote is stale after GOLD_STALE_H open hours without a newer one, so weekends and nights never count. */
function goldOpenAt(t, kind){
  if(kind === 'th'){ var b = new Date(t + 7*3600000), bw = b.getUTCDay(), m = b.getUTCHours()*60 + b.getUTCMinutes(); return bw>=1 && bw<=5 && m>=540 && m<1050; }
  var d = new Date(t), wd = d.getUTCDay(), hh = d.getUTCHours();
  return !(wd===6 || (wd===5 && hh>=22) || (wd===0 && hh<22));
}
function goldStale(iso, kind, now){
  var t = Date.parse(iso||''); now = now || Date.now();
  if(isNaN(t)) return true;
  if(now - t > 21*86400000) return true;
  var open = 0;
  for(var x = t; x < now; x += 900000){ if(goldOpenAt(x, kind)){ open += 0.25; if(open > GOLD_STALE_H) return true; } }
  return false;
}
/* a market item is used only when its as_of is newer than the embedded value's */
function goldUse(it, embIso){
  if(!it || live.offline) return null;
  var v = liveNum(it), t = Date.parse(it.as_of||''), e = Date.parse(embIso||'');
  if(v==null || !(v > 0) || isNaN(t)) return null;
  return (isNaN(e) || t > e) ? it : null;
}
function goldNum(v){ return (typeof v === 'number' && isFinite(v) && v > 0) ? v : null; }
/* every known value with its own as_of: the live item, gold_history.json and the embedded value; sorted, one per as_of */
function goldPoints(sl, tl){
  var spot = [], th = [], seenS = {}, seenT = {}, g = GOLD, gt = g.thai || {};
  function add(arr, seen, iso, v){ var t = Date.parse(iso||''); v = Number(v); if(isNaN(t) || !(v > 0) || seen[t]) return; seen[t] = 1; arr.push({t:t, v:v}); }
  if(sl) add(spot, seenS, sl.as_of, liveNum(sl));
  if(tl) add(th, seenT, tl.as_of, liveNum(tl));
  var hp = goldState.hist && Array.isArray(goldState.hist.points) ? goldState.hist.points : [];
  hp.forEach(function(p){ if(!p || typeof p !== 'object') return; add(spot, seenS, p.spot_as_of, p.spot); add(th, seenT, p.th_as_of, p.th_sell); });
  add(spot, seenS, g.as_of, g.spot_now); add(th, seenT, gt.as_of, gt.sell);
  var by = function(a, b){ return a.t - b.t; };
  return {spot:spot.sort(by), th:th.sort(by)};
}
/* the last value of the previous Bangkok day before time t */
function prevDayRef(arr, t){
  var day = bkkDay(t);
  for(var i = arr.length-1; i >= 0; i--){ if(arr[i].t < t && bkkDay(arr[i].t) < day) return (t - arr[i].t <= GOLD_REF_MAX_MS) ? arr[i] : null; }
  return null;
}
function leadPct(s){ var m = /^\s*([+\-−]?\d+(?:\.\d+)?)\s*%/.exec(String(s||'')); return m ? parseFloat(m[1].replace('−', '-')) : null; }
function goldVM(){
  var g = GOLD, th = g.thai || {}, now = Date.now();
  var sl = goldUse(goldState.live, g.as_of), tl = goldUse(goldState.liveTh, th.as_of);
  var P = goldPoints(sl, tl), vm = {sl:sl, tl:tl, P:P};
  vm.spot = sl ? liveNum(sl) : g.spot_now;
  vm.spotAsOf = sl ? sl.as_of : g.as_of;
  vm.spotStale = sl ? goldStale(sl.as_of, 'spot', now) : false;
  if(sl){
    var r = prevDayRef(P.spot, Date.parse(sl.as_of));
    if(r){ vm.dayRef = r; vm.dayPct = (vm.spot/r.v - 1)*100; }
    else { vm.dayText = String(sl.change_th || ''); vm.dayPct = leadPct(sl.change_th); vm.dayTrend = ['up','down','flat'].indexOf(sl.trend) >= 0 ? sl.trend : 'flat'; }
  } else vm.dayPct = g.change_day_pct;
  vm.peak = Math.max(g.peak, vm.spot); vm.peakLive = vm.spot > g.peak;
  vm.fromPeak = sl ? (vm.spot/vm.peak - 1)*100 : g.from_peak_pct;
  /* year low: the embedded low unless a recorded price of the same year went below it */
  vm.yearLow = {v:g.year_low, note:g.year_low_note_th || ''};
  var yr = bkkDay(Date.parse(vm.spotAsOf)).slice(0, 4);
  if(sl) P.spot.forEach(function(p){ if(bkkDay(p.t).slice(0, 4) === yr && p.v < vm.yearLow.v) vm.yearLow = {v:p.v, note:thaiDayShort(p.t) + ' ต่ำสุดใหม่ของปี'}; });

  vm.sell = tl ? liveNum(tl) : th.sell;
  vm.thAsOf = tl ? tl.as_of : th.as_of;
  vm.thStale = tl ? goldStale(tl.as_of, 'th', now) : false;
  if(tl){
    var rt = prevDayRef(P.th, Date.parse(tl.as_of));
    if(rt){ vm.thRef = rt; vm.thDay = vm.sell - rt.v; }
    else { vm.thDayText = String(tl.change_th || ''); vm.thTrend = ['up','down','flat'].indexOf(tl.trend) >= 0 ? tl.trend : 'flat'; }
  }
  /* buy / ornament: live only when the same announcement carried them (and they make sense), else the embedded value with its own date */
  var lb = tl ? goldNum(tl.buy) : null, lo = tl ? goldNum(tl.ornament_sell) : null;
  if(lb != null && !(vm.sell - lb > 0 && vm.sell - lb <= 1000)) lb = null;
  if(lo != null && !(lo > vm.sell && lo <= vm.sell + 2500)) lo = null;
  vm.buy = lb != null ? {v:lb, live:true} : {v:th.buy, live:!tl};
  vm.orn = lo != null ? {v:lo, live:true} : {v:th.ornament_sell, live:!tl};
  vm.ytd = tl && th.year_open ? (vm.sell/th.year_open - 1)*100 : th.ytd_pct;
  vm.thYearLow = th.year_low;
  var tyr = bkkDay(Date.parse(vm.thAsOf)).slice(0, 4);
  if(tl) P.th.forEach(function(p){ if(bkkDay(p.t).slice(0, 4) === tyr && p.v < vm.thYearLow) vm.thYearLow = p.v; });
  return vm;
}
var GOLD_ANALYSIS_DAY = GOLD ? thaiDate(bkkDay(Date.parse(GOLD.as_of))) : '';     /* "2 พ.ย. 2569" */
var GOLD_ANALYSIS_SHORT = GOLD ? thaiDayShort(Date.parse(GOLD.as_of)) : '';        /* "2 พ.ย." */
var GOLD_THAI_SHORT = GOLD && GOLD.thai ? thaiDayShort(Date.parse(GOLD.thai.as_of)) : GOLD_ANALYSIS_SHORT;

/* --- 2569 line chart: month-end closes, then one point per Bangkok day from the recorded prices; peak marker, support + MA200 --- */
function goldChartPts(vm){
  var g = GOLD, yr = new Date(Date.parse(g.as_of)).getUTCFullYear();
  /* point 0 = year open (31 Dec of the previous year), point i = month i's close (last day of the month) */
  var pts = g.series_2026.points.map(function(p, i){ return {t:Date.UTC(yr, i, 0, 12), v:p[1], lab:p[0], m:true}; });
  var lastDay = bkkDay(pts[pts.length-1].t), byDay = {}, days = [];
  vm.P.spot.forEach(function(p){ var d = bkkDay(p.t); if(d <= lastDay) return; if(!byDay[d]) days.push(d); byDay[d] = p; });
  days.sort().forEach(function(d){ pts.push({t:byDay[d].t, v:byDay[d].v, m:false}); });
  return pts;
}
function drawGoldLine(wrap, w, vm){
  var g = GOLD, pts = goldChartPts(vm), pk = g.series_2026.peak_marker, n = pts.length, be = new Date(Date.parse(g.as_of)).getUTCFullYear() + 543;
  wrap.innerHTML = '';
  var H = 236, M = {l:46, r:14, t:22, b:28}, iw = w - M.l - M.r, ih = H - M.t - M.b;
  var vals = pts.map(function(p){ return p.v; }).concat([pk.value, g.levels.chart_support, g.levels.ma200]);
  var lo = Math.floor((Math.min.apply(null, vals) - 120)/100)*100, hi = Math.ceil((Math.max.apply(null, vals) + 80)/100)*100;
  var t0 = pts[0].t, t1 = pts[n-1].t;
  function X(t){ return M.l + (t - t0)/(t1 - t0)*iw; }
  function Y(v){ return M.t + (hi - v)/(hi - lo)*ih; }
  var svg = svgEl('svg', {viewBox:'0 0 '+w+' '+H, width:w, height:H, role:'img', 'aria-label':'กราฟราคาทองโลกปี ' + be + ' ราคาปิดรายเดือนต่อด้วยราคารายวันล่าสุด'});
  niceTicks(lo, hi, 500).forEach(function(t){
    svg.appendChild(svgEl('line', {class:'grid', x1:M.l, x2:w-M.r, y1:Y(t), y2:Y(t)}));
    svg.appendChild(svgEl('text', {class:'ax', x:M.l-6, y:Y(t)+4, 'text-anchor':'end'}, fmtN(t)));
  });
  svg.appendChild(svgEl('text', {class:'axm', x:M.l-6, y:M.t-9, 'text-anchor':'end'}, '$/ออนซ์'));
  var months = pts.filter(function(p){ return p.m; }), every = iw/(months.length-1) < 30 ? 2 : 1;
  months.forEach(function(p, i){ if(i%every===0 || i===months.length-1) svg.appendChild(svgEl('text', {class:'axm', x:X(p.t), y:H-8, 'text-anchor':'middle'}, p.lab)); });
  var ys = Y(g.levels.chart_support), ym = Y(g.levels.ma200);
  svg.appendChild(svgEl('line', {class:'ref', x1:M.l, x2:w-M.r, y1:ys, y2:ys}));
  svg.appendChild(svgEl('text', {class:'reft', x:M.l+4, y:ys-4}, 'แนวรับ ' + fmtN(g.levels.chart_support)));
  svg.appendChild(svgEl('line', {class:'ref', x1:M.l, x2:w-M.r, y1:ym, y2:ym}));
  svg.appendChild(svgEl('text', {class:'reft', x:w-M.r, y:ym-4, 'text-anchor':'end'}, 'MA200 ' + fmtN(g.levels.ma200)));
  var d = pts.map(function(p, i){ return (i?'L':'M') + X(p.t).toFixed(1) + ' ' + Y(p.v).toFixed(1); }).join(' ');
  svg.appendChild(svgEl('path', {class:'area', d: d + ' L' + X(t1).toFixed(1) + ' ' + (M.t+ih) + ' L' + X(t0).toFixed(1) + ' ' + (M.t+ih) + ' Z'}));
  svg.appendChild(svgEl('path', {class:'ln', d:d}));
  var pi = -1; pts.forEach(function(p, i){ if(p.m && p.lab===pk.label_th) pi = i; });
  if(pi>=0){
    var xp = X(pts[pi].t);
    svg.appendChild(svgEl('line', {class:'lead', x1:xp, x2:xp, y1:Y(pk.value)+5, y2:Y(pts[pi].v)-4}));
    svg.appendChild(svgEl('circle', {class:'mk peak', cx:xp, cy:Y(pk.value), r:4.5}));
    svg.appendChild(svgEl('text', {class:'lab', x:xp+9, y:Y(pk.value)+1}, 'สถิติ $' + fmtN(pk.value)));
    svg.appendChild(svgEl('text', {class:'lab2', x:xp+9, y:Y(pk.value)+13}, thaiDate(pk.date)));
  }
  var last = pts[n-1];
  svg.appendChild(svgEl('circle', {class:'mk', cx:X(last.t), cy:Y(last.v), r:5}));
  var cur = svgEl('text', {class:'lab', x:X(last.t)-9, y:Y(last.v)+22, 'text-anchor':'end'}, '$' + fmtN(last.v));
  cur.insertBefore(svgEl('tspan', {class:'lab2'}, last.m ? 'ปิดเดือน ' : 'ล่าสุด ' + thaiDayShort(last.t) + ' '), cur.firstChild);
  svg.appendChild(cur);
  var cross = svgEl('line', {class:'cross', x1:0, x2:0, y1:M.t, y2:M.t+ih, visibility:'hidden'});
  var hov = svgEl('circle', {class:'hov', r:5, visibility:'hidden'});
  var hit = svgEl('rect', {x:M.l-12, y:0, width:iw+24, height:H, fill:'transparent'});
  svg.appendChild(cross); svg.appendChild(hov); svg.appendChild(hit);
  wrap.appendChild(svg);
  var tip = h('div', {class:'chart-tip', hidden:''}); wrap.appendChild(tip);
  function show(ev){
    var r = svg.getBoundingClientRect(), sc = r.width / w, x = (ev.clientX - r.left)/sc, i = 0, best = Infinity;
    pts.forEach(function(p, k){ var dx = Math.abs(X(p.t) - x); if(dx < best){ best = dx; i = k; } });
    var p = pts[i], xp = X(p.t);
    cross.setAttribute('x1', xp); cross.setAttribute('x2', xp); cross.setAttribute('visibility', 'visible');
    hov.setAttribute('cx', xp); hov.setAttribute('cy', Y(p.v)); hov.setAttribute('visibility', 'visible');
    var lab = !p.m ? thaiDayShort(p.t) + ' ' + (new Date(p.t + 7*3600000).getUTCFullYear() + 543) : (i===0 ? p.lab : 'ปิด ' + p.lab + ' ' + be);
    tip.innerHTML = ''; tip.appendChild(h('span', {text:lab + ' · '})); tip.appendChild(h('b', {text:'$' + fmtN(p.v)}));
    tip.hidden = false;
    var wr = wrap.getBoundingClientRect(), tw = tip.offsetWidth;
    var left = (r.left - wr.left) + xp*sc + (xp > M.l + iw/2 ? -tw-12 : 12);
    tip.style.left = Math.max(4, Math.min(wr.width - tw - 4, left)) + 'px';
    tip.style.top = Math.max(4, (r.top - wr.top) + Y(p.v)*sc - 34) + 'px';
  }
  function hide(){ cross.setAttribute('visibility', 'hidden'); hov.setAttribute('visibility', 'hidden'); tip.hidden = true; }
  svg.addEventListener('pointermove', show); svg.addEventListener('pointerdown', show);
  svg.addEventListener('pointerleave', hide); svg.addEventListener('pointercancel', hide);
}

/* --- analyst targets: dumbbell end-2569 -> end-2570, one hue + neutral --- */
function drawGoldForecast(wrap, w, spot, spotLabel){
  var g = GOLD, rows = g.forecasts.items;
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
    svg.appendChild(svgEl('text', {class:'reft', x:X(spot)+4, y:H-6}, (spotLabel || 'ล่าสุด') + ' $' + fmtN(spot)));
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
  var vm = goldState.vm || goldVM();
  var a = $('gold-chart'), b = $('gold-fc');
  if(a && a.clientWidth > 40){ var wa = a.clientWidth - 16; if(wa !== goldState.lineW){ goldState.lineW = wa; drawGoldLine(a, wa, vm); } }
  if(b && b.clientWidth > 40){ var wb = b.clientWidth - 16; if(wb !== goldState.fcW){ goldState.fcW = wb; drawGoldForecast(b, wb, vm.spot, vm.sl ? 'ล่าสุด' : 'ณ ' + GOLD_ANALYSIS_SHORT); } }
}

function goldFoldTitle(title, asof){
  return asof ? [h('span', {class:'fold-t', text:title}), h('span', {class:'fold-asof', text:'ณ ' + GOLD_ANALYSIS_SHORT})] : [h('span', {class:'fold-t', text:title})];
}
(function renderGold(){
  var v = $('view-gold');
  if(!GOLD){ v.appendChild(h('p', {text:'ไม่มีข้อมูลทองคำในชุดข้อมูลนี้', style:'color:var(--muted)'})); return; }
  var g = GOLD, th = g.thai || {}, lv = g.levels || {}, se = g.sentiment || null;
  var ANALYSIS = 'บทวิเคราะห์ ณ ' + GOLD_ANALYSIS_DAY;
  v.appendChild(h('div', {class:'gold-head'}, [
    h('h2', {text:'ทองคำ'}),
    h('div', {class:'asof'}, [h('div', {id:'gold-caption'}), h('div', {text:'ดอลลาร์สหรัฐ/ทรอยออนซ์'})])
  ]));
  function liveTag(){ return h('span', {class:'live-tag', hidden:''}, [h('span', {class:'sdot fresh'}), h('span', {class:'lt'})]); }
  function tile(id, cls, lbl, tag, sub){
    return h('div', {class:'tile' + (cls ? ' ' + cls : ''), id:id}, [
      h('div', {class:'lbl'}, tag ? [lbl, liveTag()] : [lbl]),
      h('div', {class:'val'}),
      h('div', {class:'delta'}, [h('span', {class:'tr'}), h('span', {class:'dt'})]),
      sub ? h('div', {class:'sub'}) : null,
      h('div', {class:'src'})
    ]);
  }
  v.appendChild(h('div', {class:'tiles'}, [
    tile('gold-tile-main', 'gold-main', 'ราคาทองโลก (spot)', true),
    tile('gold-tile-day', '', 'เปลี่ยนแปลงวันนี้'),
    tile('gold-tile-peak', '', 'จากจุดสูงสุดตลอดกาล'),
    tile('gold-tile-th', 'gold-main', (th.label_th||'ทองไทย') + ' ขายออก', true, true)
  ]));

  v.appendChild(h('h3', {class:'sec-title', text:'ราคาทองโลกปี 2569'}));
  v.appendChild(h('div', {class:'chart-wrap', id:'gold-chart-wrap'}, [
    h('div', {class:'chart-title'}, [h('span', {text:'ราคาปิดปลายเดือน ต่อด้วยรายวันล่าสุด (ดอลลาร์/ออนซ์)'}), h('span', {class:'note', text:(g.series_2026.note_th||'') + ' · รายวันจากระบบอัปเดตทุก 4 ชม.'})]),
    h('div', {id:'gold-chart'}),
    h('div', {class:'chart-legend'}, [
      h('span', null, [h('i'), 'ราคาปิดเดือน / รายวัน']),
      h('span', null, [h('i', {class:'dot'}), 'จุดสูงสุดระหว่างวัน']),
      h('span', null, [h('i', {class:'dash'}), 'แนวรับ ' + fmtN(lv.chart_support) + ' / MA200 ' + fmtN(lv.ma200) + ' (' + ANALYSIS + ')'])
    ])
  ]));

  v.appendChild(h('h3', {class:'sec-title', text:'เป้าหมายของนักวิเคราะห์'}));
  v.appendChild(h('div', {class:'chart-wrap'}, [
    h('div', {class:'chart-title'}, [h('span', {text:'เป้าหมายราคาสิ้นปี (ดอลลาร์/ออนซ์)'}), h('span', {class:'note', text:g.forecasts.note_th||''})]),
    h('div', {id:'gold-fc'}),
    h('div', {class:'chart-legend'}, [
      h('span', null, [h('i', {class:'dot'}), 'สิ้นปี 2569']),
      h('span', null, [h('i', {class:'dot fill'}), 'สิ้นปี 2570']),
      h('span', null, [h('i', {class:'dash'}), 'ราคาล่าสุด'])
    ])
  ]));

  function fold(title, open, body, asof){
    var dt = h('details', {class:'fold'}, [h('summary', null, goldFoldTitle(title, asof)), h('div', {class:'fold-body'}, body)]);
    if(open) dt.setAttribute('open', '');
    return dt;
  }
  function ul(items, cls){ var u = h('ul', {class:cls||'points'}); (items||[]).forEach(function(p){ u.appendChild(h('li', {text:p})); }); return u; }

  v.appendChild(h('h3', {class:'sec-title', text:'เจาะลึก'}));
  v.appendChild(h('p', {class:'static-note', id:'gold-analysis-note'}, [h('b', {text:ANALYSIS}), ' · ไม่อัปเดตอัตโนมัติ ตัวเลขในหัวข้อด้านล่างอาจต่างจากราคาสดด้านบน']));
  v.appendChild(fold((g.drivers_th && g.drivers_th.title_th) || 'ทำไมลง', true, [ul(g.drivers_th && g.drivers_th.points)], true));
  v.appendChild(fold((g.supports_th && g.supports_th.title_th) || 'แรงหนุน', false, [ul(g.supports_th && g.supports_th.points)], true));

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
    ], true));
  }

  var tbl = h('table', {class:'lv-table'}, [h('thead', null, [h('tr', null, [h('th', {text:'ระดับ ($)'}), h('th', {text:'บทบาท'}), h('th', {text:'หมายเหตุ'})])]), h('tbody', {id:'gold-lv-body'})]);
  v.appendChild(fold('ระดับเทคนิค', false, [h('div', {class:'lv-wrap'}, [tbl])], true));

  v.appendChild(fold('ทองไทย (' + (th.label_th||'96.5%') + ')', false, [
    h('div', {class:'kv', id:'gold-th-kv', style:'margin-top:0'}),
    (th.analyst_range_th || th.note_th) ? h('p', {class:'static-note', text:ANALYSIS + ' (ไม่อัปเดตอัตโนมัติ)'}) : null,
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
  ], true));

  v.appendChild(h('div', {class:'gold-foot'}, [
    h('div', null, [h('b', {text:g.disclaimer_th||''})]),
    h('div', {id:'gold-foot-times'}),
    h('div', {id:'gold-foot-src'})
  ]));

  goldPaint(false);
  if(window.ResizeObserver){ new ResizeObserver(function(){ goldLayout(); }).observe($('panel-body')); }
  else window.addEventListener('resize', goldLayout);
  setInterval(function(){ goldPaint(false); }, 60000);   /* the stale marker follows the clock */
})();

/* fill a tile; o = {val, trend, delta, sub, src:[text|node], live, stale} */
function goldSetTile(id, o){
  var tile = $(id); if(!tile) return false;
  var val = tile.querySelector('.val'), tr = tile.querySelector('.delta .tr'), dt = tile.querySelector('.delta .dt'), sub = tile.querySelector('.sub'), src = tile.querySelector('.src'), tag = tile.querySelector('.live-tag');
  var before = val.textContent;
  val.textContent = o.val;
  tr.textContent = TREND_GLYPH[o.trend] || TREND_GLYPH.flat; tr.className = 'tr ' + (o.trend || 'flat');
  dt.textContent = o.delta || '';
  if(sub){ sub.innerHTML = ''; (o.sub || []).forEach(function(s){ if(s) sub.appendChild(s.nodeType ? s : document.createTextNode(s)); }); sub.hidden = !(o.sub && o.sub.length); }
  src.innerHTML = ''; (o.src || []).forEach(function(s){ if(s) src.appendChild(s.nodeType ? s : h('span', {text:s})); });
  tile.classList.toggle('is-stale', !!o.stale);
  if(tag){
    tag.hidden = !o.live;
    tag.classList.toggle('stale', !!o.stale);
    tag.querySelector('.sdot').className = 'sdot ' + (o.stale ? 'stale' : 'fresh');
    tag.querySelector('.lt').textContent = o.stale ? 'ข้อมูลเก่า' : 'สด';
    tag.title = o.stale ? 'ไม่มีราคาใหม่เกิน ' + GOLD_STALE_H + ' ชม. ในเวลาที่ตลาดเปิด' : 'ราคาจากระบบอัปเดตอัตโนมัติ';
  }
  return before !== '' && before !== val.textContent;
}
function goldSrcLink(url){ return url ? h('a', {href:String(url), target:'_blank', rel:'noopener noreferrer', text:domain(String(url))}) : null; }
/* fill every value that can be live from goldVM(); embedded values keep their own date */
function goldPaint(flashIt){
  if(!GOLD || !$('gold-tile-main')) return;
  var g = GOLD, th = g.thai || {}, lv = g.levels || {}, vm = goldVM(), sl = vm.sl, tl = vm.tl;
  goldState.vm = vm;
  $('gold-caption').textContent = sl ? 'ราคาโลก ณ ' + thaiDateTime(vm.spotAsOf) : (g.as_of_caption_th || ('ราคาโลก ณ ' + thaiDateTime(g.as_of)));

  var dayTrend = vm.dayPct != null ? trendOf(vm.dayPct) : (vm.dayTrend || 'flat');
  var c1 = goldSetTile('gold-tile-main', {
    live:!!sl, stale:vm.spotStale, val:'$' + fmtN(vm.spot), trend:dayTrend,
    delta: !sl ? signPct(g.change_day_pct) + ' วันนี้' : vm.dayRef ? signPct(vm.dayPct) + ' จาก ' + thaiDayShort(vm.dayRef.t) : vm.dayText,
    src: sl ? ['ณ ' + thaiDateTime(vm.spotAsOf), goldSrcLink(sl.source)] : ['ณ ' + thaiDateTime(g.as_of), g.spot_note_th || '']
  });
  var low = 'ต่ำสุดปี $' + fmtN(vm.yearLow.v) + (vm.yearLow.note ? ' (' + vm.yearLow.note + ')' : '');
  goldSetTile('gold-tile-day', {
    val:signPct(vm.dayPct), trend: sl ? dayTrend : trendOf(g.change_week_pct),
    delta: !sl ? 'สัปดาห์ ' + signPct(g.change_week_pct) + ' · ต.ค. ' + signPct(g.change_oct_pct) + ' (ณ ' + GOLD_ANALYSIS_SHORT + ')'
               : vm.dayRef ? 'จาก $' + fmtN(vm.dayRef.v) + ' ค่าล่าสุดของ ' + thaiDayShort(vm.dayRef.t) : 'ยังไม่มีราคาของวันก่อนในระบบ ใช้ข้อความจากแหล่งราคา',
    src:['เปิดปี $' + fmtN(g.year_open) + ' · ' + low, sl ? 'คำนวณจากราคาสด' : '']
  });
  goldSetTile('gold-tile-peak', {
    val:signPct(vm.fromPeak), trend: vm.fromPeak < 0 ? 'down' : 'flat',
    delta:'สถิติ $' + fmtN(vm.peak) + (vm.peakLive ? ' (ราคาสด)' : ''),
    src:[vm.peakLive ? thaiDateTime(vm.spotAsOf) : thaiDate(g.peak_date), sl ? 'คำนวณจากราคาสด' : '']
  });
  var buyTxt = ['รับซื้อ ' + fmtN(vm.buy.v) + ' บาท', vm.buy.live ? null : ' ', vm.buy.live ? null : h('span', {class:'nw', text:'(ค่า ' + GOLD_THAI_SHORT + ')'})];
  var c2 = goldSetTile('gold-tile-th', {
    live:!!tl, stale:vm.thStale, val:fmtN(vm.sell),
    trend: !tl ? trendOf(th.two_day_change_baht) : vm.thRef ? trendOf(vm.thDay) : vm.thTrend,
    delta: !tl ? signN(th.two_day_change_baht, ' บาท') + ' จากปิดศุกร์' : vm.thRef ? (vm.thDay ? signN(vm.thDay, ' บาท') + ' จาก ' + thaiDayShort(vm.thRef.t) : 'ไม่เปลี่ยนจาก ' + thaiDayShort(vm.thRef.t)) : vm.thDayText,
    sub:buyTxt,
    src: tl ? ['ณ ' + thaiDateTime(vm.thAsOf), goldSrcLink(tl.source)] : ['ณ ' + thaiDateTime(th.as_of), th.source_th || '']
  });
  if(flashIt && goldState.painted){ if(c1) flash($('gold-tile-main')); if(c2) flash($('gold-tile-th')); }
  goldState.painted = true;

  /* technical levels: the levels are from the analysis; "testing" and the MA200 gap follow the current price */
  var tb = $('gold-lv-body'); tb.innerHTML = '';
  (lv.support||[]).forEach(function(s){
    var testing = s.role==='support' && vm.spot <= s.hi + 40 && vm.spot >= s.lo - 40;
    tb.appendChild(h('tr', null, [
      h('td', {class:'n', text:s.range_th}),
      h('td', null, [h('span', {class:'lv-tag ' + (s.role==='resistance' ? 'res' : testing ? 'now' : 'sup'), text:s.role==='resistance' ? 'แนวต้าน' : testing ? 'แนวรับ · กำลังทดสอบ' : 'แนวรับ'})]),
      h('td', {text:s.note_th||''})
    ]));
  });
  if(lv.ma200){ var gap = Math.round((vm.spot/lv.ma200 - 1)*100); tb.appendChild(h('tr', null, [h('td', {class:'n', text:fmtN(lv.ma200)}), h('td', null, [h('span', {class:'lv-tag', text:'MA200'})]), h('td', {text:'ราคา' + (sl ? 'ล่าสุด' : '') + (gap < 0 ? 'ต่ำกว่า' : 'สูงกว่า') + 'เส้นค่าเฉลี่ย 200 วันราว ' + Math.abs(gap) + '% (เส้น MA200 ณ ' + GOLD_ANALYSIS_SHORT + ')'})])); }
  if(lv.rsi_daily!=null) tb.appendChild(h('tr', null, [h('td', {class:'n', text:String(lv.rsi_daily)}), h('td', null, [h('span', {class:'lv-tag', text:'RSI รายวัน'})]), h('td', {text:(lv.rsi_daily < 30 ? 'อยู่ในเขตขายมากเกินไป (ต่ำกว่า 30)' : 'ใกล้เขตขายมากเกินไป (ต่ำกว่า 30)') + ' ค่า ณ ' + GOLD_ANALYSIS_SHORT})]));

  /* Thai gold block */
  var kvb = $('gold-th-kv'); kvb.innerHTML = '';
  var old = function(x){ return x.live ? '' : ' (ค่า ' + GOLD_THAI_SHORT + ')'; };
  [kv('ทองแท่ง ขายออก', fmtN(vm.sell) + ' บาท'), kv('ทองแท่ง รับซื้อ', fmtN(vm.buy.v) + ' บาท' + old(vm.buy)),
   kv('ทองรูปพรรณ ขายออก', fmtN(vm.orn.v) + ' บาท' + old(vm.orn)), kv('ปิดศุกร์ 30 ต.ค.', fmtN(th.friday_sell) + ' บาท'),
   kv('ปรับเสาร์ 31 ต.ค.', signN(th.sat_change_baht, ' บาท')), kv('ปรับอาทิตย์ 1 พ.ย.', signN(th.sun_change_baht, ' บาท')),
   kv('เปิดปี 2569', fmtN(th.year_open) + ' บาท'), kv('สถิติสูงสุด (' + (th.record_note_th||'') + ')', fmtN(th.record) + ' บาท'),
   kv('ต่ำสุดของปี', fmtN(vm.thYearLow) + ' บาท'), kv('เปลี่ยนแปลงเดือน ต.ค. (รวมเสาร์)', signN(th.oct_change_baht, ' บาท')),
   kv('ตั้งแต่ต้นปี', signPct(vm.ytd)), kv('อัปเดต', thaiDateTime(vm.thAsOf) + ' · ' + (tl ? domain(String(tl.source||'')) : (th.source_th||'')))
  ].forEach(function(e){ kvb.appendChild(e); });

  $('gold-foot-times').textContent = 'ราคาโลก ณ ' + thaiDateTime(vm.spotAsOf) + ' · ทองไทย ณ ' + thaiDateTime(vm.thAsOf) + ' · บทวิเคราะห์ ณ ' + GOLD_ANALYSIS_DAY + (g.updated_th ? ' (' + g.updated_th + ')' : '') + ' · ชุดข้อมูลรายเดือนเป็นค่าโดยประมาณ';
  var liveSrc = [sl && sl.source, tl && tl.source].filter(Boolean).map(function(u){ return domain(String(u)); }).filter(function(d, i, a){ return a.indexOf(d) === i; });
  $('gold-foot-src').textContent = 'แหล่งที่มา: ' + (g.sources||[]).join(' · ') + (liveSrc.length ? ' · ราคาสด: ' + liveSrc.join(', ') : '');

  /* charts redraw only when their data changed */
  var cp = goldChartPts(vm), lineSig = cp.length + ':' + cp[cp.length-1].t + ':' + cp[cp.length-1].v;
  if(lineSig !== goldState.lineSig){ goldState.lineSig = lineSig; goldState.lineW = 0; }
  var fcSig = vm.spot + ':' + !!sl;
  if(fcSig !== goldState.fcSig){ goldState.fcSig = fcSig; goldState.fcW = 0; }
  goldLayout();
}

/* live layer hooks: market.json items (key gold|xau in $/oz, gold_th in baht) and gold_history.json */
function goldLive(items){
  if(!GOLD) return;
  var it = null, itTh = null;
  (items||[]).forEach(function(x){ if(!x || typeof x !== 'object') return; if(!it && (x.key==='gold' || x.key==='xau')) it = x; if(!itTh && x.key==='gold_th') itTh = x; });
  goldState.live = (it && !live.offline) ? it : null; goldState.liveTh = (itTh && !live.offline) ? itTh : null;
  goldPaint(true);
}
function goldHistory(doc){
  if(!GOLD) return;
  goldState.hist = (doc && Array.isArray(doc.points)) ? doc : null;
  goldPaint(false);
}
