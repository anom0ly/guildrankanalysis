// Guild Pull Analytics dashboard. Reads data/index.json, then the selected
// tier's snapshot, and draws everything client side. No build step.
(function () {
  "use strict";

  var COLORS = ["var(--b1)", "var(--b2)", "var(--b3)", "var(--b4)"];
  var METRICS = [
    { key: "pulls_to_kill", name: "Pulls to kill", hint: "Fewer is faster", fmt: num },
    { key: "nights_to_kill", name: "Raid nights to kill", hint: "Fewer is faster", fmt: num },
    { key: "combat_hours", name: "Time on boss", hint: "Combat hours", fmt: function (v) { return v.toFixed(1) + "h"; } },
    { key: "item_level", name: "Item level on kill", hint: "Raid average. Gap shown vs top 100", fmt: function (v) { return v.toFixed(1); } }
  ];
  var REPO = "https://github.com/anom0ly/guildrankanalysis";

  var $ = function (id) { return document.getElementById(id); };
  var index = null;
  var snap = null;
  var state = { tier: null, region: "all", boss: null, week: null, hidden: {} };

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
    if (q.get("week") && !isNaN(+q.get("week"))) state.week = +q.get("week") - 1;
    (q.get("hide") || "").split(",").filter(Boolean).forEach(function (b) { state.hidden[b] = true; });
  }
  function writeURL() {
    var q = new URLSearchParams();
    q.set("tier", state.tier);
    q.set("region", state.region);
    q.set("boss", state.boss);
    if (state.week !== snap.weeks.length - 1) q.set("week", state.week + 1);
    var hide = Object.keys(state.hidden).filter(function (k) { return state.hidden[k]; });
    if (hide.length) q.set("hide", hide.join(","));
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

  function fillTierSelect() {
    var sel = $("tier");
    sel.innerHTML = index.tiers.map(function (t) {
      var label = t.name + (t.current ? " (live)" : "") + (t.snapshot ? "" : " (no data yet)");
      return '<option value="' + esc(t.key) + '"' + (t.snapshot ? "" : " disabled") + ">" + esc(label) + "</option>";
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

    $("brackets").innerHTML = snap.brackets.map(function (b, i) {
      return '<button type="button" class="chip" data-bracket="' + esc(b.label) + '" aria-pressed="' + !state.hidden[b.label] +
        '"><span class="dot" style="background:' + COLORS[i] + '"></span>' + esc(b.label) + "</button>";
    }).join("");
  }

  function visibleBrackets() {
    return snap.brackets.map(function (b, i) { return { label: b.label, color: COLORS[i], top: i === 0 }; })
      .filter(function (b) { return !state.hidden[b.label]; });
  }

  // A bracket x boss cell as it stood at the end of the selected week.
  function cellAt(bossSlug, bracket) {
    var c = snap.views[state.region].bosses[bossSlug][bracket];
    return c.weekly ? c.weekly[state.week] : c;
  }

  function multText(m, v) {
    if (v === null || v === undefined) return "";
    if (m === "item_level") return (v >= 0 ? "+" : "") + v.toFixed(1);
    return v.toFixed(1) + "×";
  }

  function renderCards() {
    var brackets = visibleBrackets();
    var bossName = snap.bosses.filter(function (b) { return b.slug === state.boss; })[0].name;
    $("cards-title").textContent = bossName + ": median per rank bracket";
    $("cards").innerHTML = METRICS.map(function (m) {
      var cells = brackets.map(function (b) { return cellAt(state.boss, b.label); });
      var vals = cells.map(function (c) { return c.median[m.key]; }).filter(function (v) { return v !== null; });
      var lo = 0, hi = Math.max.apply(null, vals.concat([0]));
      if (m.key === "item_level" && vals.length) {
        lo = Math.floor(Math.min.apply(null, vals)) - 5;
        hi = Math.ceil(hi) + 1;
      }
      var rows = brackets.map(function (b, i) {
        var c = cells[i], v = c.median[m.key], n = c.n[m.key];
        var width = v === null || hi <= lo ? 0 : Math.max(2, Math.round((v - lo) / (hi - lo) * 100));
        var text = v === null ? "–" : esc(m.fmt(v));
        var mult = b.top ? "" : multText(m.key, c.vs_top[m.key]);
        var nText = "n " + n + (v === null && n < snap.rules.min_sample ? " (needs " + snap.rules.min_sample + ")" : "");
        return '<div class="row"><span class="row-label">' + esc(b.label) + "</span>" +
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
      } else {
        foot = "Logs only, so the sample is guilds with the kill in public logs.";
      }
      return '<div class="card"><div><div class="card-name">' + m.name + '</div><div class="card-hint">' + m.hint +
        '</div></div><div class="rows">' + rows + '</div><div class="card-foot">' + foot + "</div></div>";
    }).join("");
  }

  function renderHeat() {
    var brackets = visibleBrackets();
    var head = "<thead><tr><th scope=\"col\">Bracket</th>" + snap.bosses.map(function (b) {
      var sel = b.slug === state.boss ? ' style="color:var(--text)"' : "";
      return '<th scope="col" title="' + esc(b.name) + '"' + sel + ">" + esc(b.name) + "</th>";
    }).join("") + "</tr></thead>";
    var cols = snap.bosses.map(function (b) {
      var vals = brackets.map(function (br) { return cellAt(b.slug, br.label).median.pulls_to_kill; });
      var present = vals.filter(function (v) { return v !== null; });
      return { vals: vals, max: Math.max.apply(null, present.concat([0])) };
    });
    var body = "<tbody>" + brackets.map(function (br, r) {
      return '<tr><th scope="row"><span class="dot" style="background:' + br.color + '"></span>' + esc(br.label) + "</th>" +
        snap.bosses.map(function (b, ci) {
          var v = cols[ci].vals[r];
          var cell = cellAt(b.slug, br.label);
          var sel = b.slug === state.boss ? " sel" : "";
          if (v === null) {
            return '<td class="empty' + sel + '" title="' + esc(b.name) + ": " + cell.n.pulls_to_kill + ' measured kills">–</td>';
          }
          var idx = Math.min(5, Math.floor(v / cols[ci].max * 5.999));
          var mult = br.top ? "" : multText("pulls_to_kill", cell.vs_top.pulls_to_kill);
          return '<td class="h' + idx + sel + '" title="' + esc(b.name) + ": n " + cell.n.pulls_to_kill + '">' + esc(num(v)) +
            (mult ? '<span class="mult">' + mult + "</span>" : "") + "</td>";
        }).join("") + "</tr>";
    }).join("") + "</tbody>";
    $("heat").innerHTML = head + body;
  }

  function renderChart() {
    var bossName = snap.bosses.filter(function (b) { return b.slug === state.boss; })[0].name;
    $("chart-title").textContent = bossName + " kills over the tier";
    var brackets = visibleBrackets();
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
        s += '<path d="' + d + '" fill="none" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" style="stroke:' + br.color + '"></path>';
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
    s += '<div class="legend">' + brackets.map(function (br) {
      var v = snap.views[state.region].bosses[state.boss][br.label].kill_share_weekly[state.week];
      return '<span><span class="dot" style="background:' + br.color + '"></span>' + esc(br.label) +
        (v === null || v === undefined ? "" : " " + pct(v)) + "</span>";
    }).join("") + "</div>";
    $("chart").innerHTML = s;
  }

  function render() {
    if (!snap) return;
    var t = tierEntry(state.tier);
    $("subtitle").textContent = snap.tier.name + " · Week " + (state.week + 1) + " of tier" +
      (t && t.updated_at ? " · Last refreshed " + fmtDate(t.updated_at) : "");
    renderCards();
    renderHeat();
    renderChart();
    writeURL();
  }

  function loadTier() {
    showStatus();
    var t = tierEntry(state.tier);
    if (!t || !t.snapshot) {
      snap = null;
      $("content").hidden = true;
      // Keep the tier picker only when another tier has data to switch to.
      $("filters").hidden = !index.tiers.some(function (x) { return x.snapshot; });
      $("subtitle").textContent = t ? t.name + " · No data yet" : "No data yet";
      return Promise.resolve();
    }
    return getJSON("data/" + t.snapshot).then(function (s) {
      snap = s;
      fillSnapshotControls();
      $("filters").hidden = false;
      $("content").hidden = false;
      render();
    });
  }

  function bind() {
    $("tier").addEventListener("change", function (e) { state.tier = e.target.value; state.week = null; loadTier(); });
    $("region").addEventListener("change", function (e) { state.region = e.target.value; render(); });
    $("boss").addEventListener("change", function (e) { state.boss = e.target.value; render(); });
    $("week").addEventListener("change", function (e) { state.week = +e.target.value; render(); });
    $("brackets").addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-bracket]");
      if (!btn) return;
      var label = btn.getAttribute("data-bracket");
      var shown = snap.brackets.filter(function (b) { return !state.hidden[b.label]; }).length;
      if (!state.hidden[label] && shown === 1) return; // keep at least one bracket
      state.hidden[label] = !state.hidden[label];
      btn.setAttribute("aria-pressed", String(!state.hidden[label]));
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
