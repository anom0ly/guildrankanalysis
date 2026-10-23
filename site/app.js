// Guild Pull Analytics dashboard. Reads data/index.json, then the selected
// tier's snapshot, and draws everything client side. No build step.
(function () {
  "use strict";

  var COLORS = ["var(--b1)", "var(--b2)", "var(--b3)", "var(--b4)", "var(--b5)", "var(--b6)", "var(--b7)", "var(--b8)", "var(--b9)"];
  // Kill chart lines shown until the viewer picks others; nine at once tangle.
  var CHART_DEFAULT = ["1-200", "401-600", "1001-1200", "2001-3000"];
  function hours(v) { return v.toFixed(1) + "h"; }
  function ilvl(v) { return v.toFixed(1); }
  function share(v) { return Math.round(v) + "%"; }
  function rate(v) { return v.toFixed(2); }
  function big(v) { return v >= 1e6 ? (v / 1e6).toFixed(2) + "M" : Math.round(v / 1e3) + "k"; }
  // diff: compared with 1-200 as a difference (points or item levels) instead of a multiple.
  var METRICS = [
    { key: "pulls_to_kill", group: "Progress", name: "Pulls to kill", hint: "Fewer is faster", fmt: num },
    { key: "nights_to_kill", group: "Progress", name: "Raid nights to kill", hint: "Fewer is faster", fmt: num },
    { key: "combat_hours", group: "Progress", name: "Time on boss", hint: "Combat hours", fmt: hours },
    { key: "pulls_to_sub10", group: "Learning curve", name: "Pulls to a sub-10% wipe", hint: "First pull with under 10% of the fight left", fmt: num },
    { key: "closeout_pulls", group: "Learning curve", name: "Close-out pulls", hint: "From the first sub-10% wipe to the kill", fmt: num },
    { key: "longest_plateau", group: "Wipe depth", name: "Longest plateau", hint: "Most pulls in a row without new progress", fmt: num },
    { key: "late_wipe_share", group: "Wipe depth", name: "Late wipes", hint: "Share of wipes in the kill stage. Gap in points vs 1-200", fmt: share, diff: true },
    { key: "pulls_per_hour", group: "Schedule", name: "Pulls per hour", hint: "Pulls per hour of raid time on the boss. More is faster", fmt: ilvl },
    { key: "item_level", group: "Gear", name: "Item level on kill", hint: "Raid average. Gap shown vs 1-200", fmt: ilvl, diff: true },
    { key: "first_pull_ilvl", group: "Gear", name: "Item level on first pull", hint: "Raid average. Gap shown vs 1-200", fmt: ilvl, diff: true },
    { key: "ilvl_gained", group: "Gear", name: "Item level gained", hint: "Kill minus first pull. Gap shown vs 1-200", fmt: ilvl, diff: true },
    { key: "deaths_per_pull", group: "Deaths", name: "Deaths per pull", hint: "Player deaths per progression pull", fmt: rate },
    { key: "early_deaths_per_pull", group: "Deaths", name: "Early deaths per pull", hint: "Deaths in the first minute of a pull", fmt: rate },
    { key: "avoidable_deaths_per_pull", group: "Deaths", name: "Avoidable deaths per pull", hint: "Deaths to the hand-picked avoidable ability", fmt: rate },
    { key: "fast_loss_share", group: "Deaths", name: "Fast collapses", hint: "Share of wipes over within 90 s of the third death. Gap in points vs 1-200", fmt: share, diff: true },
    { key: "players_used", group: "Roster", name: "Players used", hint: "Different players across the progression pulls", fmt: num },
    { key: "raid_dps_on_kill", group: "Throughput", name: "Raid DPS on kill", hint: "Everyone's DPS added up, first kill", fmt: big },
    { key: "raid_hps_on_kill", group: "Throughput", name: "Healer HPS on kill", hint: "Healers' HPS added up, first kill", fmt: big },
    { key: "comp_similarity", group: "Throughput", name: "Comp match", hint: "How close the kill's spec mix is to 1-200's average (100% is the same). Gap in points", fmt: share, diff: true }
  ];
  var GROUPS = ["Progress", "Learning curve", "Wipe depth", "Schedule", "Gear", "Deaths", "Roster", "Throughput"];
  var KILL_KEYS = ["raid_dps_on_kill", "raid_hps_on_kill", "comp_similarity"];
  var DEATH_GROUPS = ["Deaths", "Roster"];
  var TIER_METRICS = [
    { key: "hours_per_week", name: "Hours / week", fmt: function (v) { return v.toFixed(1); } },
    { key: "nights_per_week", name: "Nights / week", fmt: function (v) { return v.toFixed(1); } },
    { key: "regulars", name: "Players", fmt: num }
  ];
  function metricInfo(key) { return METRICS.filter(function (m) { return m.key === key; })[0]; }
  var REPO = "https://github.com/anom0ly/guildrankanalysis";

  var $ = function (id) { return document.getElementById(id); };
  var index = null;
  var snap = null;
  var VIEWS = ["brackets", "h2h", "peers"];
  // view: the tab; a and b: Raider.IO guild ids picked in the guild views (a is the peers view's guild).
  var state = { tier: null, region: "all", boss: null, week: null, hidden: {}, chart: null, metric: "pulls_to_kill",
                view: "brackets", a: null, b: null };

  function num(v) { return Math.abs(v - Math.round(v)) < 0.05 ? String(Math.round(v)) : v.toFixed(1); }
  function pct(v) { return Math.round(v * 100) + "%"; }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmtDate(iso) {
    var d = new Date(iso);
    return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  function fmtDay(iso) {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function getJSON(path) {
    return fetch(path, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error(path + ": " + r.status);
      return r.json();
    });
  }

  // URL state, so a view can be shared as a link.
  function readURL() {
    var q = new URLSearchParams(location.search);
    if (q.get("tier")) state.tier = q.get("tier");
    if (["all", "us", "eu"].indexOf(q.get("region")) >= 0) state.region = q.get("region");
    if (q.get("boss")) state.boss = q.get("boss");
    if (metricInfo(q.get("metric"))) state.metric = q.get("metric");
    if (q.get("week") && !isNaN(+q.get("week"))) state.week = +q.get("week") - 1;
    (q.get("hide") || "").split(",").filter(Boolean).forEach(function (b) { state.hidden[b] = true; });
    if (VIEWS.indexOf(q.get("view")) >= 0) state.view = q.get("view");
    ["a", "b"].forEach(function (k) { if (q.get(k) && !isNaN(+q.get(k))) state[k] = +q.get(k); });
  }
  function writeURL() {
    var q = new URLSearchParams();
    q.set("tier", state.tier);
    q.set("region", state.region);
    q.set("boss", state.boss);
    if (state.metric !== "pulls_to_kill") q.set("metric", state.metric);
    if (state.week !== snap.weeks.length - 1) q.set("week", state.week + 1);
    var hide = Object.keys(state.hidden).filter(function (k) { return state.hidden[k]; });
    if (hide.length) q.set("hide", hide.join(","));
    if (state.view !== "brackets") q.set("view", state.view);
    if (state.a !== null) q.set("a", state.a);
    if (state.b !== null) q.set("b", state.b);
    history.replaceState(null, "", "?" + q.toString());
  }

  function tierEntry(key) {
    return index.tiers.filter(function (t) { return t.key === key; })[0];
  }

  function showStatus() {
    var run = index.run;
    var t = tierEntry(state.tier);
    var banner = $("banner"), pill = $("status-pill");
    banner.hidden = true;
    pill.hidden = true;
    if (!run || run.complete || run.tier !== state.tier) return;
    var share = run.total ? run.done / run.total : 0;
    if (!t || !t.snapshot) {
      banner.hidden = false;
      banner.innerHTML = "<strong>First load in progress: " + run.done.toLocaleString() + " of " +
        run.total.toLocaleString() + " guilds</strong>" +
        "Guilds are loaded in rank order in chunks of about five hours, so the numbers appear once every bracket is complete. " +
        "Started " + esc(fmtDate(run.started_at)) + "." +
        '<div class="progress" role="progressbar" aria-label="First load progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' +
        Math.round(share * 100) + '"><div style="width:' + (share * 100).toFixed(1) + '%"></div></div>';
    } else {
      pill.hidden = false;
      pill.textContent = "Refreshing: " + run.done.toLocaleString() + " of " + run.total.toLocaleString() + " guilds";
    }
  }

  // The second read of the logs (roster, deaths, comp) fills in over a few days.
  function enrichNote() {
    var t = tierEntry(state.tier), e = t && t.enrich;
    if (!e || !e.total || e.done >= e.total) return "";
    return " · Deaths and roster: " + Math.floor(100 * e.done / e.total) + "% of logs read";
  }

  // How a tier is labelled in the picker: live, final, or how far its
  // one-time load has got.
  function tierState(t) {
    if (t.current) return t.snapshot ? "live" : "first load running";
    var b = t.backfill;
    if (t.snapshot) return "final";
    if (b && b.state === "loading" && b.total) return "loading " + Math.floor(100 * b.done / b.total) + "%";
    if (b && b.state === "queued") return "queued";
    return "no data yet";
  }

  function fillTierSelect() {
    var sel = $("tier"), groups = [], byGroup = {};
    index.tiers.forEach(function (t) {
      var g = t.expansion || "";
      if (!byGroup[g]) { byGroup[g] = []; groups.push(g); }
      byGroup[g].push(t);
    });
    sel.innerHTML = groups.map(function (g) {
      var opts = byGroup[g].map(function (t) {
        return '<option value="' + esc(t.key) + '"' + (t.snapshot ? "" : " disabled") + ">" +
          esc(t.name + " · " + tierState(t)) + "</option>";
      }).join("");
      return g ? '<optgroup label="' + esc(g) + '">' + opts + "</optgroup>" : opts;
    }).join("");
    sel.value = state.tier;
  }

  function fillSnapshotControls() {
    var boss = $("boss");
    boss.innerHTML = snap.bosses.map(function (b, i) {
      var last = i === snap.bosses.length - 1 ? " (final boss)" : "";
      return '<option value="' + esc(b.slug) + '">' + esc(b.name + last) + "</option>";
    }).join("");
    if (!snap.bosses.some(function (b) { return b.slug === state.boss; })) {
      state.boss = snap.bosses[snap.bosses.length - 1].slug;
    }
    boss.value = state.boss;

    var week = $("week");
    week.innerHTML = snap.weeks.map(function (w, i) {
      var last = i === snap.weeks.length - 1;
      return '<option value="' + i + '">Week ' + (i + 1) + (last ? " (latest)" : " (to " + esc(fmtDay(w)) + ")") + "</option>";
    }).join("");
    if (state.week === null || state.week < 0 || state.week >= snap.weeks.length) state.week = snap.weeks.length - 1;
    week.value = String(state.week);

    if (!state.chart) {
      state.chart = {};
      snap.brackets.forEach(function (b) { state.chart[b.label] = CHART_DEFAULT.indexOf(b.label) >= 0; });
      if (!snap.brackets.some(function (b) { return state.chart[b.label]; })) state.chart[snap.brackets[0].label] = true;
    }
  }

  // Brackets in display order, the top bracket's slices right under it.
  // Brackets with no guilds in this region are left out.
  function allBrackets() {
    var sizes = snap.views[state.region].bracket_sizes;
    var out = [];
    snap.brackets.forEach(function (b, i) {
      out.push({ label: b.label, color: COLORS[i] || COLORS[COLORS.length - 1], top: i === 0, sub: false });
      if (i === 0) {
        (snap.slices || []).forEach(function (s) { out.push({ label: s.label, color: COLORS[0], top: false, sub: true }); });
      }
    });
    return out.filter(function (b) { return sizes[b.label] > 0; });
  }

  function visibleBrackets() {
    return allBrackets().filter(function (b) { return !state.hidden[b.label]; });
  }

  function dot(b) {
    return '<span class="dot' + (b.sub ? " ring" : "") + '" style="' + (b.sub ? "border-color:" : "background:") + b.color + '"></span>';
  }

  function renderChips() {
    $("brackets").innerHTML = allBrackets().map(function (b) {
      return '<button type="button" class="chip' + (b.sub ? " sub" : "") + '" data-bracket="' + esc(b.label) + '" aria-pressed="' +
        !state.hidden[b.label] + '">' + dot(b) + esc(b.label) + "</button>";
    }).join("");
  }

  // A bracket x boss cell as it stood at the end of the selected week.
  function cellAt(bossSlug, bracket) {
    var c = snap.views[state.region].bosses[bossSlug][bracket];
    return c.weekly ? c.weekly[state.week] : c;
  }

  function multText(m, v) {
    if (v === null || v === undefined) return "";
    if (metricInfo(m) && metricInfo(m).diff) return (v >= 0 ? "+" : "") + v.toFixed(1);
    return v.toFixed(1) + "×";
  }

  // Metrics this snapshot has (an older snapshot may predate some).
  function activeMetrics() {
    return METRICS.filter(function (m) { return snap.metrics.indexOf(m.key) >= 0; });
  }
  function med(c, key) { var v = c.median[key]; return v === undefined ? null : v; }
  function bossName() { return snap.bosses.filter(function (b) { return b.slug === state.boss; })[0].name; }

  function card(m, brackets) {
    var cells = brackets.map(function (b) { return cellAt(state.boss, b.label); });
    var vals = cells.map(function (c) { return med(c, m.key); }).filter(function (v) { return v !== null; });
    var lo = 0, hi = Math.max.apply(null, vals.concat([0]));
    if ((m.key === "item_level" || m.key === "first_pull_ilvl") && vals.length) {
      lo = Math.floor(Math.min.apply(null, vals)) - 5;
      hi = Math.ceil(hi) + 1;
    }
    var rows = brackets.map(function (b, i) {
      var c = cells[i], v = med(c, m.key), n = c.n[m.key] || 0;
      var width = v === null || hi <= lo ? 0 : Math.max(2, Math.round((v - lo) / (hi - lo) * 100));
      var text = v === null ? "–" : esc(m.fmt(v));
      var mult = b.top ? "" : multText(m.key, c.vs_top[m.key]);
      var nText = "n " + n + (v === null && n < snap.rules.min_sample ? " (needs " + snap.rules.min_sample + ")" : "");
      return '<div class="row' + (b.sub ? " sub" : "") + '"><span class="row-label">' + esc(b.label) + "</span>" +
        '<div class="bar"><div style="width:' + width + "%;background:" + b.color + '"></div></div>' +
        '<span class="val">' + text + (mult ? ' <span class="mult">' + mult + "</span>" : "") +
        '<span class="n">' + nText + "</span></span></div>";
    }).join("");
    var foot;
    if (m.key === "pulls_to_kill") {
      foot = "Pull counts from Raider.IO: " + brackets.map(function (b, i) {
        var c = cells[i], s = c.pulls_source, used = c.used;
        return esc(b.label) + " " + (used ? pct((s.rio_fill + s.rio_corrected) / used) : "–");
      }).join(" · ");
    } else if (KILL_KEYS.indexOf(m.key) >= 0) {
      foot = "From Warcraft Logs rankings of each guild's first kill.";
    } else if (DEATH_GROUPS.indexOf(m.group) >= 0) {
      foot = "Logs only. A guild counts once every one of its pulls on the boss has had the second read.";
    } else {
      foot = "Logs only, so the sample is guilds with the kill in public logs.";
    }
    return '<div class="card"><div><div class="card-name">' + m.name + '</div><div class="card-hint">' + m.hint +
      '</div></div><div class="rows">' + rows + '</div><div class="card-foot">' + foot + "</div></div>";
  }

  function renderCards() {
    var brackets = visibleBrackets();
    var metrics = activeMetrics();
    var group = metricInfo(state.metric).group;
    $("cards-title").textContent = bossName() + ": " + group.toLowerCase() + ", median per rank bracket";
    // The cards follow the heatmap's metric: its group's metrics for the picked boss.
    $("cards").innerHTML = [group].map(function (g) {
      var ms = metrics.filter(function (m) { return m.group === g; });
      if (!ms.length) return "";
      return '<div class="card-group"><div class="cards">' +
        ms.map(function (m) { return card(m, brackets); }).join("") + "</div></div>";
    }).join("");
  }

  function renderPicker() {
    var metrics = activeMetrics();
    if (!metricInfo(state.metric) || snap.metrics.indexOf(state.metric) < 0) state.metric = "pulls_to_kill";
    $("metric-picker").innerHTML = GROUPS.map(function (g) {
      var ms = metrics.filter(function (m) { return m.group === g; });
      if (!ms.length) return "";
      return '<div class="pgroup"><span class="label">' + esc(g) + '</span><div class="chips">' + ms.map(function (m) {
        return '<button type="button" class="chip small" data-metric="' + m.key + '" aria-pressed="' + (m.key === state.metric) + '">' +
          esc(m.name) + "</button>";
      }).join("") + "</div></div>";
    }).join("");
    var m = metricInfo(state.metric);
    $("heat-title").textContent = "Median " + m.name.charAt(0).toLowerCase() + m.name.slice(1) + ", every boss";
    $("heat-note").textContent = m.diff
      ? "The small figure is the difference from 1-200 (the Hall of Fame guilds)."
      : "The small figure is the multiple of 1-200's median (the Hall of Fame guilds).";
  }

  function renderHeat() {
    var brackets = visibleBrackets();
    var m = metricInfo(state.metric);
    var summary = snap.views[state.region].tier_summary;
    var head = "<thead><tr><th scope=\"col\">Bracket</th>" + snap.bosses.map(function (b) {
      var sel = b.slug === state.boss ? ' style="color:var(--text)"' : "";
      return '<th scope="col" class="boss" data-boss="' + esc(b.slug) + '" title="' + esc(b.name) + '"' + sel + ">" + esc(b.name) + "</th>";
    }).join("") + (summary ? TIER_METRICS.map(function (t, i) {
      return '<th scope="col" class="tiercol' + (i === 0 ? " first" : "") + '">' + esc(t.name) + "</th>";
    }).join("") : "") + "</tr></thead>";
    var cols = snap.bosses.map(function (b) {
      var vals = brackets.map(function (br) { return med(cellAt(b.slug, br.label), m.key); });
      var present = vals.filter(function (v) { return v !== null; });
      return { vals: vals, max: Math.max.apply(null, present.concat([0])), min: Math.min.apply(null, present.concat([Infinity])) };
    });
    var body = "<tbody>" + brackets.map(function (br, r) {
      var tiers = "";
      if (summary) {
        var t = summary[br.label];
        tiers = TIER_METRICS.map(function (tm, i) {
          var v = t ? t.median[tm.key] : null;
          var mult = br.top || !t ? "" : multText(tm.key, t.vs_top[tm.key]);
          var tn = t ? (typeof t.n === "object" ? t.n[tm.key] || 0 : t.n) : 0;
          return '<td class="tiercol' + (i === 0 ? " first" : "") + '" title="Whole tier: n ' + tn + ' guilds">' +
            (v === null ? "–" : esc(tm.fmt(v)) + (mult ? '<span class="mult">' + mult + "</span>" : "")) + "</td>";
        }).join("");
      }
      return "<tr" + (br.sub ? ' class="sub"' : "") + '><th scope="row">' + dot(br) + esc(br.label) + "</th>" +
        snap.bosses.map(function (b, ci) {
          var v = cols[ci].vals[r];
          var cell = cellAt(b.slug, br.label);
          var sel = b.slug === state.boss ? " sel" : "";
          var n = cell.n[m.key] || 0;
          if (v === null) {
            return '<td class="empty' + sel + '" data-boss="' + esc(b.slug) + '" title="' + esc(b.name) + ": " + n + ' measured kills">–</td>';
          }
          var c = cols[ci], t;
          if (m.diff) t = c.max > c.min ? (v - c.min) / (c.max - c.min) : 0;
          else t = c.max ? v / c.max : 0;
          var idx = Math.min(5, Math.max(0, Math.floor(t * 5.999)));
          var mult = br.top ? "" : multText(m.key, cell.vs_top[m.key]);
          return '<td class="h' + idx + sel + '" data-boss="' + esc(b.slug) + '" title="' + esc(b.name) + ": n " + n + '">' + esc(m.fmt(v)) +
            (mult ? '<span class="mult">' + mult + "</span>" : "") + "</td>";
        }).join("") + tiers + "</tr>";
    }).join("") + "</tbody>";
    $("heat").innerHTML = head + body;
  }

  // Shared SVG frame for the boss detail charts.
  function frame(W, H) {
    return '<svg viewBox="0 0 ' + W + " " + H + '" role="img"';
  }
  function tick(x, y, text, anchor) {
    return '<text x="' + x + '" y="' + y + '" text-anchor="' + (anchor || "middle") + '" font-size="12" style="fill:var(--muted)">' + esc(text) + "</text>";
  }
  function hline(x0, x1, y, strong) {
    return '<line x1="' + x0 + '" x2="' + x1 + '" y1="' + y + '" y2="' + y + '" style="stroke:' + (strong ? "var(--control)" : "var(--track)") + '"></line>';
  }
  function chartLegend(options) {
    return '<div class="legend" role="group" aria-label="Lines shown">' + options.map(function (br) {
      return '<button type="button" class="lg" data-line="' + esc(br.label) + '" aria-pressed="' + !!state.chart[br.label] + '">' +
        dot(br) + esc(br.label) + "</button>";
    }).join("") + "</div>";
  }

  function renderCurve() {
    var el = $("curve");
    $("curve-title").textContent = bossName() + ": learning curve";
    var options = visibleBrackets().filter(function (br) { return snap.views[state.region].bosses[state.boss][br.label].curve; });
    var lines = options.filter(function (br) { return state.chart[br.label]; });
    if (!options.length) { el.innerHTML = '<p class="none">No bracket has 10 guilds with this kill in public logs yet.</p>'; return; }
    var curves = lines.map(function (br) { return snap.views[state.region].bosses[state.boss][br.label].curve; });
    var maxN = Math.max.apply(null, curves.map(function (c) { return c[c.length - 1][0]; }).concat([10]));
    var W = 560, H = 300, x0 = 56, x1 = 540, y0 = 16, y1 = 260;
    var px = function (n) { return x0 + (n - 1) * (x1 - x0) / Math.max(1, maxN - 1); };
    var py = function (v) { return y1 - v / 100 * (y1 - y0); };
    var s = frame(W, H) + ' aria-label="Line chart: median share of the fight left on the best pull so far, by pull number, one line per rank bracket">';
    [100, 75, 50, 25, 0].forEach(function (g) { s += hline(x0, x1, py(g), g === 100) + tick(x0 - 8, py(g) + 4, g + "%", "end"); });
    s += '<line x1="' + x0 + '" x2="' + x1 + '" y1="' + py(10) + '" y2="' + py(10) + '" stroke-dasharray="3 4" style="stroke:var(--muted)"></line>';
    s += tick(x1, py(10) - 5, "10% left", "end");
    var step = Math.max(1, Math.round(maxN / 6 / 10) * 10 || 1);
    for (var n = 0; n <= maxN; n += step) if (n >= 1 || step > 1) s += tick(px(Math.max(1, n)), 280, String(Math.max(1, n)));
    s += tick((x0 + x1) / 2, 296, "pull number");
    lines.forEach(function (br, i) {
      var c = curves[i];
      var d = c.map(function (pt, j) { return (j ? "L" : "M") + px(pt[0]).toFixed(1) + " " + py(pt[1]).toFixed(1); }).join(" ");
      s += '<path d="' + d + '" fill="none" stroke-width="2.5" stroke-linejoin="round"' + (br.sub ? ' stroke-dasharray="6 5"' : "") +
        ' style="stroke:' + br.color + '"><title>' + esc(br.label) + "</title></path>";
    });
    s += "</svg>";
    el.innerHTML = s + chartLegend(options);
  }

  var STAGE_COLORS = ["var(--h1)", "var(--h3)", "var(--h4)", "var(--h5)", "var(--h2)"];
  var BAND_NAMES = { "75-100": "75-100% left", "50-75": "50-75% left", "25-50": "25-50% left", "0-25": "under 25% left" };

  function renderWipes() {
    var el = $("wipes");
    $("wipes-title").textContent = bossName() + ": where wipes ended";
    var brackets = visibleBrackets().filter(function (br) { return snap.views[state.region].bosses[state.boss][br.label].wipe_mix; });
    if (!brackets.length) { el.innerHTML = '<p class="none">No bracket has 10 guilds with wipes on this boss in public logs yet.</p>'; return; }
    var mixes = brackets.map(function (br) { return snap.views[state.region].bosses[state.boss][br.label].wipe_mix; });
    var keys = Object.keys(mixes[0].shares);
    var byStage = mixes[0].by === "phase";
    var names = (snap.stages || {})[state.boss] || {};
    var label = function (k) { return byStage ? (names[k] || "Stage " + k) : BAND_NAMES[k]; };
    var rows = brackets.map(function (br, i) {
      var sh = mixes[i].shares;
      var segs = keys.map(function (k, j) {
        var v = sh[k] || 0;
        return v > 0 ? '<div style="width:' + (v * 100).toFixed(1) + "%;background:" + STAGE_COLORS[j % STAGE_COLORS.length] +
          '" title="' + esc(label(k)) + ": " + pct(v) + '"></div>' : "";
      }).join("");
      return '<div class="row' + (br.sub ? " sub" : "") + '"><span class="row-label">' + esc(br.label) + '</span><div class="stack">' + segs +
        '</div><span class="val">' + pct(sh[keys[keys.length - 1]] || 0) + '<span class="n">n ' + mixes[i].n + "</span></span></div>";
    }).join("");
    var legend = '<div class="legend">' + keys.map(function (k, j) {
      return '<span><span class="dot sq" style="background:' + STAGE_COLORS[j % STAGE_COLORS.length] + '"></span>' + esc(label(k)) + "</span>";
    }).join("") + "</div>";
    el.innerHTML = legend + '<div class="rows">' + rows + "</div>";
  }

  function renderGear() {
    var el = $("gear");
    $("gear-title").textContent = bossName() + ": item level, first pull to kill";
    var brackets = visibleBrackets().filter(function (br) {
      var c = cellAt(state.boss, br.label);
      return med(c, "first_pull_ilvl") !== null && med(c, "item_level") !== null;
    });
    if (!brackets.length) { el.innerHTML = '<p class="none">No bracket has 10 guilds with both pulls in public logs yet.</p>'; return; }
    var pts = brackets.map(function (br) { var c = cellAt(state.boss, br.label); return [med(c, "first_pull_ilvl"), med(c, "item_level")]; });
    var all = [].concat.apply([], pts);
    var lo = Math.floor(Math.min.apply(null, all)) - 1, hi = Math.ceil(Math.max.apply(null, all)) + 1;
    var rowH = 26, W = 560, x0 = 96, x1 = 500, top = 24, H = top + brackets.length * rowH + 8;
    var px = function (v) { return x0 + (v - lo) / (hi - lo) * (x1 - x0); };
    var s = frame(W, H) + ' aria-label="Item level on the first pull and on the kill, per rank bracket">';
    var stepI = Math.max(1, Math.round((hi - lo) / 6));
    for (var v = lo; v <= hi; v += stepI) {
      s += '<line x1="' + px(v) + '" x2="' + px(v) + '" y1="' + (top - 6) + '" y2="' + (H - 4) + '" style="stroke:var(--track)"></line>' + tick(px(v), top - 10, String(v));
    }
    brackets.forEach(function (br, i) {
      var y = top + i * rowH + rowH / 2, a = pts[i][0], b = pts[i][1];
      s += '<text x="' + (x0 - 10) + '" y="' + (y + 4) + '" text-anchor="end" font-size="12" style="fill:var(--text)">' + esc(br.label) + "</text>";
      s += '<line x1="' + px(a) + '" x2="' + px(b) + '" y1="' + y + '" y2="' + y + '" stroke-width="3" style="stroke:' + br.color + ';stroke-opacity:0.5"></line>';
      s += '<circle cx="' + px(a) + '" cy="' + y + '" r="5" style="fill:var(--surface);stroke:' + br.color + ';stroke-width:2"><title>' + esc(br.label) + " first pull " + a.toFixed(1) + "</title></circle>";
      s += '<circle cx="' + px(b) + '" cy="' + y + '" r="5" style="fill:' + br.color + '"><title>' + esc(br.label) + " kill " + b.toFixed(1) + "</title></circle>";
      s += '<text x="' + (x1 + 12) + '" y="' + (y + 4) + '" font-size="12" style="fill:var(--muted)">+' + (b - a).toFixed(1) + "</text>";
    });
    s += "</svg>";
    el.innerHTML = '<div class="legend"><span><span class="dot ring" style="border-color:var(--muted)"></span>First pull</span>' +
      '<span><span class="dot" style="background:var(--muted)"></span>Kill</span><span>+n: item levels gained</span></div>' + s;
  }

  function detailCell(br) { return snap.views[state.region].bosses[state.boss][br.label]; }

  // Columns are brackets, so each table reads across like the heatmap reads down.
  function bracketTable(brackets, rows, caption) {
    return '<div class="scroll"><table class="grid"><caption class="sr">' + esc(caption) + "</caption><thead><tr><th scope=\"col\"></th>" +
      brackets.map(function (br) { return '<th scope="col">' + dot(br) + esc(br.label) + "</th>"; }).join("") + "</tr></thead><tbody>" +
      rows.join("") + "</tbody></table></div>";
  }

  function renderKillers() {
    var el = $("killers");
    $("killers-title").textContent = bossName() + ": what players die to";
    var list = (snap.killers || {})[state.boss] || [];
    var brackets = visibleBrackets().filter(function (br) { return (detailCell(br) || {}).killers; });
    if (!list.length || !brackets.length) {
      el.innerHTML = '<p class="none">Not enough guilds have had the second read of their logs on this boss yet.</p>'; return;
    }
    var rows = list.map(function (a) {
      return '<tr><th scope="row">' + (a.name ? esc(a.name) : "Ability " + a.id) + (a.avoidable ? ' <span class="tag">avoidable</span>' : "") + "</th>" +
        brackets.map(function (br) { var v = detailCell(br).killers.per_pull[String(a.id)]; return "<td>" + (v === undefined ? "–" : rate(v)) + "</td>"; }).join("") + "</tr>";
    });
    rows.push('<tr class="total"><th scope="row">All deaths</th>' + brackets.map(function (br) {
      var k = detailCell(br).killers; return "<td>" + rate(k.all_per_pull) + '<span class="n">n ' + k.n + "</span></td>";
    }).join("") + "</tr>");
    el.innerHTML = bracketTable(brackets, rows, "Deaths per pull by killing ability and rank bracket");
  }

  function renderComp() {
    var el = $("comp");
    $("comp-title").textContent = bossName() + ": raid comp on the kill";
    var brackets = visibleBrackets().filter(function (br) { return (detailCell(br) || {}).specs; });
    if (!brackets.length) { el.innerHTML = '<p class="none">Not enough first kills have rankings on this boss yet.</p>'; return; }
    // Specs in the order the first bracket shown uses them most.
    var specs = Object.keys(detailCell(brackets[0]).specs.mean).slice(0, 15);
    var rows = specs.map(function (k) {
      return '<tr><th scope="row">' + esc(k.replace("-", " ").replace(/([a-z])([A-Z])/g, "$1 $2")) + "</th>" + brackets.map(function (br) {
        var v = detailCell(br).specs.mean[k]; return "<td>" + (v ? v.toFixed(1) : "–") + "</td>";
      }).join("") + "</tr>";
    });
    rows.push('<tr class="total"><th scope="row">Kills</th>' + brackets.map(function (br) { return "<td>" + detailCell(br).specs.n + "</td>"; }).join("") + "</tr>");
    el.innerHTML = bracketTable(brackets, rows, "Average players of each spec on the first kill, per rank bracket");
  }

  var ROSTER_ROWS = [
    { key: "regulars", name: "Regular players", fmt: num },
    { key: "core_coverage", name: "Pulls with the core 16 of 20", fmt: share },
    { key: "new_per_week", name: "New regulars per week", fmt: function (v) { return v.toFixed(1); } }
  ];

  function renderRoster() {
    var el = $("roster");
    var summary = snap.views[state.region].tier_summary;
    var brackets = visibleBrackets().filter(function (br) { var t = summary[br.label]; return t && t.median.regulars != null; });
    if (!brackets.length) { el.innerHTML = '<p class="none">Not enough guilds have had the second read of their logs yet.</p>'; return; }
    var rows = ROSTER_ROWS.map(function (r) {
      return '<tr><th scope="row">' + esc(r.name) + "</th>" + brackets.map(function (br) {
        var v = summary[br.label].median[r.key]; return "<td>" + (v === null || v === undefined ? "–" : esc(r.fmt(v))) + "</td>";
      }).join("") + "</tr>";
    });
    rows.push('<tr class="total"><th scope="row">Guilds</th>' + brackets.map(function (br) {
      return "<td>" + (summary[br.label].n.regulars || 0) + "</td>";
    }).join("") + "</tr>");
    el.innerHTML = bracketTable(brackets, rows, "Roster stability medians per rank bracket, whole tier");
  }

  function renderChart() {
    var bossName = snap.bosses.filter(function (b) { return b.slug === state.boss; })[0].name;
    $("chart-title").textContent = bossName + " kills over the tier";
    var options = visibleBrackets();
    var brackets = options.filter(function (b) { return state.chart[b.label]; });
    var weeks = snap.weeks.length;
    var W = 560, H = 300, x0 = 56, x1 = 540, y0 = 20, y1 = 260;
    var px = function (i) { return weeks > 1 ? x0 + i * (x1 - x0) / (weeks - 1) : (x0 + x1) / 2; };
    var py = function (v) { return y1 - v * (y1 - y0); };
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Line chart: share of guilds with a ' +
      esc(bossName) + ' kill by week, one line per rank bracket">';
    [0, 0.25, 0.5, 0.75, 1].forEach(function (g) {
      s += '<line x1="' + x0 + '" x2="' + x1 + '" y1="' + py(g) + '" y2="' + py(g) + '" style="stroke:' +
        (g === 0 ? "var(--control)" : "var(--track)") + '"></line>';
      s += '<text x="' + (x0 - 8) + '" y="' + (py(g) + 4) + '" text-anchor="end" font-size="12" style="fill:var(--muted)">' + pct(g) + "</text>";
    });
    var step = weeks > 12 ? 2 : 1;
    for (var i = 0; i < weeks; i += step) {
      s += '<text x="' + px(i) + '" y="284" text-anchor="middle" font-size="12" style="fill:var(--muted)">W' + (i + 1) + "</text>";
    }
    brackets.forEach(function (br) {
      var series = snap.views[state.region].bosses[state.boss][br.label].kill_share_weekly;
      var d = series.map(function (v, i) { return v === null ? null : (i === 0 ? "M" : "L") + px(i).toFixed(1) + " " + py(v).toFixed(1); })
        .filter(Boolean).join(" ").replace(/^L/, "M");
      if (d) {
        s += '<path d="' + d + '" fill="none" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"' +
          (br.sub ? ' stroke-dasharray="6 5"' : "") + ' style="stroke:' + br.color + '"></path>';
      }
      var v = series[state.week];
      if (v !== null && v !== undefined) {
        s += '<circle cx="' + px(state.week) + '" cy="' + py(v) + '" r="4.5" style="fill:' + br.color + ';stroke:var(--surface);stroke-width:2"><title>' +
          esc(br.label) + ": " + pct(v) + " by week " + (state.week + 1) + "</title></circle>";
      }
    });
    s += '<line x1="' + px(state.week) + '" x2="' + px(state.week) + '" y1="' + y0 + '" y2="' + y1 + '" stroke-dasharray="3 4" style="stroke:var(--muted)"></line>';
    s += '<text x="' + px(state.week) + '" y="14" text-anchor="middle" font-size="11" style="fill:var(--muted)">As of</text>';
    s += "</svg>";
    s += '<div class="legend" role="group" aria-label="Lines shown">' + options.map(function (br) {
      var v = snap.views[state.region].bosses[state.boss][br.label].kill_share_weekly[state.week];
      return '<button type="button" class="lg" data-line="' + esc(br.label) + '" aria-pressed="' + !!state.chart[br.label] + '">' +
        dot(br) + esc(br.label) + (v === null || v === undefined ? "" : " " + pct(v)) + "</button>";
    }).join("") + "</div>";
    $("chart").innerHTML = s;
  }

  function render() {
    if (!snap) return;
    var t = tierEntry(state.tier);
    if (t && !t.current) {
      // A finished tier: its ranks are final and its data doesn't change.
      $("subtitle").textContent = snap.tier.name + " · Final ranks · Week " + (state.week + 1) +
        " of " + snap.weeks.length;
    } else {
      $("subtitle").textContent = snap.tier.name + " · Week " + (state.week + 1) + " of tier" +
        (t && t.updated_at ? " · Last refreshed " + fmtDate(t.updated_at) : "") + enrichNote();
    }
    VIEWS.forEach(function (v) { $("tab-" + v).setAttribute("aria-selected", String(v === state.view)); });
    var brackets = state.view === "brackets";
    $("content").hidden = !brackets;
    $("guild-view").hidden = brackets;
    // Boss and bracket filters only apply to the bracket view; the guild views show every boss.
    $("boss-field").hidden = !brackets;
    $("brackets-field").hidden = !brackets;
    if (!brackets) {
      window.GuildCompare.render(compareAPI);
      writeURL();
      return;
    }
    renderChips();
    renderCards();
    renderPicker();
    renderHeat();
    renderChart();
    renderCurve();
    renderWipes();
    renderGear();
    renderKillers();
    renderComp();
    renderRoster();
    writeURL();
  }

  function loadTier() {
    showStatus();
    var t = tierEntry(state.tier);
    if (!t || !t.snapshot) {
      snap = null;
      $("content").hidden = true;
      $("guild-view").hidden = true;
      $("tabs").hidden = true;
      // Keep the tier picker only when another tier has data to switch to.
      $("filters").hidden = !index.tiers.some(function (x) { return x.snapshot; });
      $("subtitle").textContent = t ? t.name + " · " + tierState(t) : "No data yet";
      return Promise.resolve();
    }
    return getJSON("data/" + t.snapshot).then(function (s) {
      snap = s;
      fillSnapshotControls();
      $("filters").hidden = false;
      $("tabs").hidden = false;
      render();
    });
  }

  // What compare.js gets to work with.
  var compareAPI = {
    state: state, metrics: METRICS, groups: GROUPS, metricInfo: metricInfo, esc: esc, getJSON: getJSON,
    get snap() { return snap; },
    tierEntry: function () { return tierEntry(state.tier); },
    // End of the picked week in ms, or null for the latest week (everything counts).
    weekEnd: function () { return state.week === snap.weeks.length - 1 ? null : new Date(snap.weeks[state.week]).getTime(); },
    changed: render
  };

  function bind() {
    $("tabs").addEventListener("click", function (e) {
      var tab = e.target.closest("[data-view]");
      if (!tab) return;
      state.view = tab.getAttribute("data-view");
      render();
    });
    $("tier").addEventListener("change", function (e) { state.tier = e.target.value; state.week = null; state.chart = null; loadTier(); });
    $("region").addEventListener("change", function (e) { state.region = e.target.value; render(); });
    $("boss").addEventListener("change", function (e) { state.boss = e.target.value; render(); });
    $("week").addEventListener("change", function (e) { state.week = +e.target.value; render(); });
    $("brackets").addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-bracket]");
      if (!btn) return;
      var label = btn.getAttribute("data-bracket");
      var shown = visibleBrackets().length;
      if (!state.hidden[label] && shown === 1) return; // keep at least one bracket
      state.hidden[label] = !state.hidden[label];
      render();
    });
    // The kill chart and the learning curve share one line selection.
    ["chart", "curve"].forEach(function (id) {
      $(id).addEventListener("click", function (e) {
        var btn = e.target.closest("button[data-line]");
        if (!btn) return;
        var label = btn.getAttribute("data-line");
        state.chart[label] = !state.chart[label];
        renderChart();
        renderCurve();
      });
    });
    $("metric-picker").addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-metric]");
      if (!btn) return;
      state.metric = btn.getAttribute("data-metric");
      render();
    });
    $("heat").addEventListener("click", function (e) {
      var cell = e.target.closest("[data-boss]");
      if (!cell) return;
      state.boss = cell.getAttribute("data-boss");
      $("boss").value = state.boss;
      render();
    });
  }

  function start() {
    readURL();
    bind();
    $("region").value = state.region;
    $("foot").innerHTML = 'Refreshed daily at 10:00 UTC from Raider.IO and Warcraft Logs. <a href="' + REPO + '">Source and method</a>.';
    getJSON("data/index.json").then(function (idx) {
      index = idx;
      var withData = idx.tiers.filter(function (t) { return t.snapshot; });
      if (!tierEntry(state.tier)) {
        var cur = idx.tiers.filter(function (t) { return t.current; })[0];
        state.tier = (withData[0] || cur || idx.tiers[0]).key;
      }
      fillTierSelect();
      return loadTier();
    }).catch(function (err) {
      $("subtitle").textContent = "No data published yet";
      $("filters").hidden = true;
      var banner = $("banner");
      banner.hidden = false;
      banner.innerHTML = "<strong>No data yet</strong>The first data refresh hasn't been published. Check back after the next run.";
      if (window.console) console.error(err);
    });
  }

  start();
})();
