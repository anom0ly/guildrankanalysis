// Head to head and Against peers views. Loads the tier's compare.json (one
// row per guild, the same per boss numbers the bracket medians use) the first
// time one of the views opens, and works out peers and medians client side.
(function () {
  "use strict";

  // Which way is better, for the difference text and the peer score.
  var LOWER_BETTER = {
    pulls_to_kill: true, nights_to_kill: true, combat_hours: true, pulls_to_sub10: true,
    closeout_pulls: true, longest_plateau: true, late_wipe_share: true
  };
  var HIGHER_BETTER = { pulls_per_hour: true };
  // Scaled from a little under the lower value, since item levels sit far from 0.
  var OFFSET_SCALE = { item_level: true, first_pull_ilvl: true };
  var DIFF_UNITS = { late_wipe_share: " pts" };
  var RESULTS = 8;

  var cache = {};  // tier key -> Promise of the parsed file
  var api = null;

  function esc(s) { return api.esc(s); }
  function $(id) { return document.getElementById(id); }

  function realmName(slug) {
    return String(slug || "").split("-").map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1); }).join(" ");
  }
  function norm(s) { return String(s).toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, ""); }

  function parse(raw) {
    var f = raw.fields, at = {};
    f.forEach(function (k, i) { at[k] = i; });
    var guilds = raw.guilds.map(function (r) {
      return {
        id: r[at.rio_guild_id], name: r[at.name], realm: r[at.realm], region: r[at.region],
        world: r[at.world_rank], regionRank: r[at.region_rank], status: raw.statuses[r[at.status]],
        key: norm(r[at.name]),
        bosses: r[at.bosses].map(function (b) {
          if (!b) return null;
          var out = { kill: b[0], source: b[1] >= 0 ? raw.sources[b[1]] : null, v: {} };
          raw.metrics.forEach(function (m, i) { out.v[m] = b.length > 2 ? b[2 + i] : null; });
          return out;
        }),
        tier: r[at.tier] ? { hours_per_week: r[at.tier][0], nights_per_week: r[at.tier][1] } : null
      };
    });
    var byId = {};
    guilds.forEach(function (g) { byId[g.id] = g; });
    return { raw: raw, guilds: guilds, byId: byId };
  }

  function load(t) {
    if (!cache[t.key]) {
      cache[t.key] = api.getJSON("data/" + t.compare).then(parse);
      cache[t.key].catch(function () { delete cache[t.key]; });
    }
    return cache[t.key];
  }

  // The guild's numbers on boss i as they stood at the end of the picked week.
  function bossAt(g, i) {
    var b = g.bosses[i];
    if (!b) return null;
    var end = api.weekEnd();
    if (end !== null && b.kill !== null && b.kill * 1000 > end) return null;
    return b;
  }
  function value(g, i, m) {
    var b = bossAt(g, i);
    if (!b || b.source === null) return null;
    var v = b.v[m];
    return v === undefined ? null : v;
  }
  function killed(g, i) { return bossAt(g, i) !== null; }
  function killCount(g) {
    var n = 0;
    g.bosses.forEach(function (_, i) { if (killed(g, i)) n++; });
    return n;
  }
  function median(xs) {
    var s = xs.slice().sort(function (a, b) { return a - b; }), n = s.length;
    return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  }
  function quantile(s, q) {  // s sorted
    var p = (s.length - 1) * q, lo = Math.floor(p), hi = Math.ceil(p);
    return s[lo] + (s[hi] - s[lo]) * (p - lo);
  }

  function rankOf(g, region) {
    if (region === "all") return g.world;
    return g.region === region ? g.regionRank : null;
  }
  function rankLabel(region) { return region === "all" ? "world rank" : region.toUpperCase() + " rank"; }
  function guildLine(g) {
    return g.region.toUpperCase() + " · " + realmName(g.realm) + " · #" + g.world.toLocaleString();
  }

  // ---- Guild search ----

  function searchField(slot, label, g, swatch) {
    var current = g
      ? '<span class="gs-current"><span class="dot sq" style="background:' + swatch + '"></span><strong>' + esc(g.name) +
        '</strong><span class="gs-meta">' + esc(guildLine(g)) + "</span></span>"
      : '<span class="gs-current none">No guild picked</span>';
    return '<div class="field gsearch" data-slot="' + slot + '"><label for="gs-' + slot + '">' + esc(label) + "</label>" +
      '<input id="gs-' + slot + '" type="search" autocomplete="off" spellcheck="false" placeholder="Search guild name" ' +
      'role="combobox" aria-expanded="false" aria-controls="gs-' + slot + '-list" aria-autocomplete="list">' +
      '<ul class="gs-list" id="gs-' + slot + '-list" role="listbox" hidden></ul>' + current + "</div>";
  }

  function matches(data, q) {
    q = norm(q.trim());
    if (!q) return [];
    // Exact names first, then names starting with the text, then the rest;
    // each in world rank order, which is the file's order.
    var exact = [], starts = [], has = [];
    for (var i = 0; i < data.guilds.length && exact.length < RESULTS; i++) {
      var g = data.guilds[i], at = g.key.indexOf(q);
      if (g.key === q) exact.push(g);
      else if (at === 0) starts.push(g);
      else if (at > 0) has.push(g);
    }
    return exact.concat(starts, has).slice(0, RESULTS);
  }

  function showResults(data, input) {
    var list = input.parentNode.querySelector(".gs-list");
    var found = matches(data, input.value);
    if (!input.value.trim()) { list.hidden = true; input.setAttribute("aria-expanded", "false"); return; }
    list.innerHTML = found.length ? found.map(function (g, i) {
      return '<li role="option" id="' + input.id + "-o" + i + '" data-id="' + g.id + '"' + (i === 0 ? ' aria-selected="true"' : "") + ">" +
        "<span>" + esc(g.name) + '</span><span class="gs-meta">' + esc(guildLine(g)) +
        (g.status === "matched" ? "" : " · pulls only") + "</span></li>";
    }).join("") : '<li class="gs-empty">No guild by that name in this tier</li>';
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function moveSelection(input, step) {
    var opts = [].slice.call(input.parentNode.querySelectorAll("li[data-id]"));
    if (!opts.length) return;
    var at = opts.findIndex(function (o) { return o.getAttribute("aria-selected") === "true"; });
    var next = Math.max(0, Math.min(opts.length - 1, at + step));
    opts.forEach(function (o, i) { o.setAttribute("aria-selected", i === next ? "true" : "false"); });
    input.setAttribute("aria-activedescendant", opts[next].id);
  }

  function pick(slot, id) {
    api.state[slot] = id;
    api.changed();
  }

  function bindSearch(data) {
    var root = $("guild-view");
    root.oninput = function (e) {
      if (e.target.matches(".gsearch input")) showResults(data, e.target);
    };
    root.onkeydown = function (e) {
      if (!e.target.matches(".gsearch input")) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); moveSelection(e.target, e.key === "ArrowDown" ? 1 : -1); }
      if (e.key === "Enter") {
        var sel = e.target.parentNode.querySelector('li[aria-selected="true"]');
        if (sel) pick(e.target.parentNode.getAttribute("data-slot"), +sel.getAttribute("data-id"));
      }
      if (e.key === "Escape") { e.target.value = ""; showResults(data, e.target); }
    };
    root.onclick = function (e) {
      var li = e.target.closest(".gs-list li[data-id]");
      if (li) { pick(li.closest(".gsearch").getAttribute("data-slot"), +li.getAttribute("data-id")); return; }
      var mb = e.target.closest("button[data-metric]");
      if (mb) { api.state.metric = mb.getAttribute("data-metric"); api.changed(); return; }
      var swap = e.target.closest("[data-swap]");
      if (swap) { var a = api.state.a; api.state.a = api.state.b; api.state.b = a; api.changed(); }
    };
  }

  // ---- Shared pieces ----

  function metricPicker(data) {
    var m = api.metricInfo(api.state.metric);
    return '<div class="picker" id="cmp-metrics" role="group" aria-label="Metric">' + api.groups.map(function (grp) {
      var ms = api.metrics.filter(function (x) { return x.group === grp && data.raw.metrics.indexOf(x.key) >= 0; });
      if (!ms.length) return "";
      return '<div class="pgroup"><span class="label">' + esc(grp) + '</span><div class="chips">' + ms.map(function (x) {
        return '<button type="button" class="chip small" data-metric="' + x.key + '" aria-pressed="' + (x.key === m.key) + '">' + esc(x.name) + "</button>";
      }).join("") + "</div></div>";
    }).join("") + "</div>";
  }

  function stat(k, v) { return '<div class="stat"><span class="k">' + esc(k) + '</span><span class="v">' + v + "</span></div>"; }
  function vs(a, b) { return '<span class="ga">' + a + '</span> <span class="vs">vs</span> <span class="gb">' + b + "</span>"; }
  function bossNames() { return api.snap.bosses.map(function (b) { return b.name; }); }

  // Why a guild has no number: no kill by then, or not in public logs.
  function missing(g, i) {
    return killed(g, i) ? '<span class="muted" title="Not in public logs">–</span>' : '<span class="muted">no kill</span>';
  }

  // ---- Head to head ----

  function difference(m, A, B, a, b) {
    if (a === null || b === null) return '<span class="muted">–</span>';
    if (a === b) return "Even";
    var winA;
    if (m.diff) {
      var d = Math.abs(a - b), hi = a > b ? A : B;
      var unit = DIFF_UNITS[m.key] || (OFFSET_SCALE[m.key] || m.key === "ilvl_gained" ? " ilvl" : "");
      return '<b class="' + (hi === A ? "ga" : "gb") + '">' + esc(hi.name) + "</b> +" + d.toFixed(1) + unit;
    }
    if (HIGHER_BETTER[m.key]) {
      winA = a > b;
      return '<b class="' + (winA ? "ga" : "gb") + '">' + esc((winA ? A : B).name) + "</b> " +
        Math.round((Math.max(a, b) / Math.min(a, b) - 1) * 100) + "% more";
    }
    winA = a < b;
    return '<b class="' + (winA ? "ga" : "gb") + '">' + esc((winA ? A : B).name) + "</b> needed " +
      Math.round((1 - Math.min(a, b) / Math.max(a, b)) * 100) + "% fewer";
  }

  function bars(m, a, b) {
    var lo = 0, hi = Math.max(a || 0, b || 0);
    if (OFFSET_SCALE[m.key] && a !== null && b !== null) lo = Math.min(a, b) - 4;
    function w(v) { return v === null || hi <= lo ? 0 : Math.max(3, 100 * (v - lo) / (hi - lo)); }
    return '<div class="duo"><div class="bar l"><div style="width:' + w(a).toFixed(1) + '%"></div></div>' +
      '<div class="bar r"><div style="width:' + w(b).toFixed(1) + '%"></div></div></div>';
  }

  function sumOf(g, m) {
    var s = 0, n = 0;
    g.bosses.forEach(function (_, i) { var v = value(g, i, m); if (v !== null) { s += v; n++; } });
    return n ? s : null;
  }

  function renderH2H(data) {
    var A = data.byId[api.state.a], B = data.byId[api.state.b];
    var m = api.metricInfo(api.state.metric);
    var head = '<div class="panel-head"><h2>' + (A && B ? esc(A.name) + " vs " + esc(B.name) : "Head to head") + "</h2>" +
      "<p>Pick two guilds. Each boss shows both side by side, scaled to the larger of the two. Only kills count, " +
      "with the same rules as the bracket view. Guilds without public logs have pull counts from Raider.IO only.</p></div>";
    var pickers = '<div class="controls">' + searchField("a", "Guild A", A, "var(--ga)") +
      '<button type="button" class="swap" data-swap aria-label="Swap guilds" title="Swap guilds">⇄</button>' +
      searchField("b", "Guild B", B, "var(--gb)") + "</div>";
    if (!A || !B) {
      return head + pickers + '<p class="none">Search for ' + (A || B ? "one more guild" : "two guilds") +
        " to compare them boss by boss.</p>";
    }
    var fmt = function (v, f) { return v === null ? "–" : f(v); };
    var one = function (v) { return v.toFixed(1); };
    var summary = '<div class="summary">' +
      stat("World rank", vs(A.world.toLocaleString(), B.world.toLocaleString())) +
      stat("Region rank", vs(A.region.toUpperCase() + " " + fmt(A.regionRank, String), B.region.toUpperCase() + " " + fmt(B.regionRank, String))) +
      stat("Bosses killed", vs(killCount(A) + "/" + A.bosses.length, killCount(B) + "/" + B.bosses.length)) +
      stat("Pulls, all kills", vs(fmt(sumOf(A, "pulls_to_kill"), function (v) { return v.toLocaleString(); }),
                                  fmt(sumOf(B, "pulls_to_kill"), function (v) { return v.toLocaleString(); }))) +
      stat("Hours / week", vs(A.tier ? one(A.tier.hours_per_week) : "–", B.tier ? one(B.tier.hours_per_week) : "–")) +
      stat("Nights / week", vs(A.tier ? one(A.tier.nights_per_week) : "–", B.tier ? one(B.tier.nights_per_week) : "–")) +
      "</div>";
    var names = bossNames();
    var rows = names.map(function (name, i) {
      var a = value(A, i, m.key), b = value(B, i, m.key);
      return '<tr><th scope="row">' + esc(name) + '</th><td class="num ga">' + (a === null ? missing(A, i) : esc(m.fmt(a))) + "</td>" +
        "<td>" + bars(m, a, b) + '</td><td class="num gb">' + (b === null ? missing(B, i) : esc(m.fmt(b))) + "</td>" +
        '<td class="verdict">' + difference(m, A, B, a, b) + "</td></tr>";
    }).join("");
    var table = '<div class="scroll"><table class="cmp"><thead><tr><th scope="col">Boss</th><th scope="col" class="num">' + esc(A.name) +
      '</th><th scope="col" class="mid">' + esc(m.name) + '</th><th scope="col" class="num">' + esc(B.name) +
      '</th><th scope="col">Difference</th></tr></thead><tbody>' + rows + "</tbody></table></div>";
    var foot = '<p class="note">' + esc(m.hint) + ". A dash means the kill isn't in public logs, or the logs miss nights " +
      "(Raider.IO's pull count is then used for pulls only). Hours and nights per week are the whole tier, from the latest data.</p>";
    return head + pickers + summary + metricPicker(data) + table + foot;
  }

  // ---- Against peers ----

  function peerGroup(data, g, region) {
    var r = rankOf(g, region), w = data.raw.peer_window;
    if (r === null) return null;
    var peers = data.guilds.filter(function (p) {
      if (p === g) return false;
      var pr = rankOf(p, region);
      return pr !== null && Math.abs(pr - r) <= w;
    });
    return { rank: r, lo: Math.max(1, r - w), hi: r + w, peers: peers };
  }

  // Peer numbers on one boss, with the bracket view's low-pull rule: guilds
  // under a quarter of the median pull count are left out as incomplete logs.
  function peerStats(data, peers, i, m) {
    var withPulls = peers.filter(function (p) { return value(p, i, "pulls_to_kill") !== null; });
    if (!withPulls.length) return { n: 0, vals: [] };
    var floor = data.raw.low_pull_fraction * median(withPulls.map(function (p) { return value(p, i, "pulls_to_kill"); }));
    var kept = withPulls.filter(function (p) { return value(p, i, "pulls_to_kill") >= floor; });
    var vals = kept.map(function (p) { return value(p, i, m); }).filter(function (v) { return v !== null; }).sort(function (a, b) { return a - b; });
    var out = { n: vals.length, vals: vals, floor: floor };
    if (vals.length >= data.raw.min_sample) {
      out.med = median(vals);
      out.p25 = quantile(vals, 0.25);
      out.p75 = quantile(vals, 0.75);
    }
    return out;
  }

  // Share of peers this guild beat, or (no better direction) sat above.
  function score(m, s, mine) {
    if (mine === null || s.med === undefined) return null;
    var n = s.vals.filter(function (v) { return LOWER_BETTER[m] ? v > mine : v < mine; }).length;
    return Math.round(100 * n / s.vals.length);
  }

  function strip(s, mine, m) {
    var W = 300, H = 30, vals = s.vals;
    var lo = Math.min(vals[0], mine === null ? vals[0] : mine);
    var hi = Math.max(vals[Math.floor((vals.length - 1) * 0.95)], mine === null ? 0 : mine) * 1.04;
    if (OFFSET_SCALE[m.key]) hi = Math.max(vals[vals.length - 1], mine === null ? -Infinity : mine) + 0.5;
    var x = function (v) { return 6 + (W - 12) * (Math.min(v, hi) - lo) / ((hi - lo) || 1); };
    var seen = {}, dots = "";
    vals.forEach(function (v) {
      var px = Math.round(x(v)), k = (seen[px] = (seen[px] || 0) + 1);
      dots += '<circle cx="' + px + '" cy="' + (15 + ((k % 5) - 2) * 3.2).toFixed(1) + '" r="2.2" style="fill:var(--peer)" fill-opacity="0.75"></circle>';
    });
    var me = mine === null ? "" : '<path d="M' + x(mine).toFixed(1) + " 5 L" + (x(mine) + 8).toFixed(1) + " 15 L" + x(mine).toFixed(1) + " 25 L" +
      (x(mine) - 8).toFixed(1) + ' 15Z" style="fill:var(--gb);stroke:var(--surface)" stroke-width="1.5"></path>';
    return '<svg class="strip" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + s.n + " peers, median " + esc(m.fmt(s.med)) + '">' +
      '<rect x="' + x(s.p25).toFixed(1) + '" y="7" width="' + Math.max(2, x(s.p75) - x(s.p25)).toFixed(1) + '" height="16" rx="3" style="fill:var(--band)"></rect>' +
      dots + '<rect x="' + (x(s.med) - 1).toFixed(1) + '" y="3" width="2" height="24" style="fill:var(--text)"></rect>' + me + "</svg>";
  }

  function scorePill(m, p) {
    if (p === null) return '<span class="muted">–</span>';
    var cls = "pct";
    if (LOWER_BETTER[m] || HIGHER_BETTER[m]) cls += p >= 60 ? " good" : p <= 40 ? " bad" : "";
    return '<span class="' + cls + '">' + p + "%</span>";
  }

  function renderPeers(data) {
    var G = data.byId[api.state.a];
    var m = api.metricInfo(api.state.metric);
    var region = api.state.region;
    var directional = !!(LOWER_BETTER[m.key] || HIGHER_BETTER[m.key]);
    var head = '<div class="panel-head"><h2>' + (G ? esc(G.name) + " against its peers" : "Against peers") + "</h2>";
    var pickers = '<div class="controls">' + searchField("a", "Guild", G, "var(--gb)") + "</div>";
    if (!G) {
      return head + "<p>Pick a guild to see how it compares with the guilds ranked within " + data.raw.peer_window +
        " places of it.</p></div>" + pickers + '<p class="none">Search for a guild to start.</p>';
    }
    var grp = peerGroup(data, G, region);
    if (!grp) {
      return head + "</div>" + pickers + '<p class="none">' + esc(G.name) + " is a " + esc(G.region.toUpperCase()) +
        " guild. Set Region to All or " + esc(G.region.toUpperCase()) + " to see its peers.</p>";
    }
    var logged = grp.peers.filter(function (p) { return p.status === "matched"; }).length;
    head += "<p>Peers are the " + grp.peers.length.toLocaleString() + " guilds ranked " + grp.lo.toLocaleString() + " to " +
      grp.hi.toLocaleString() + " by " + rankLabel(region) + ", " + data.raw.peer_window + " either side of " + esc(G.name) +
      " (#" + grp.rank.toLocaleString() + "). " + logged.toLocaleString() + " of them have public logs. The rest count toward pulls only, " +
      "through Raider.IO. Each row places " + esc(G.name) + " among the peers with that kill.</p></div>";
    var names = bossNames();
    var stats = names.map(function (_, i) { return peerStats(data, grp.peers, i, m.key); });
    var mine = names.map(function (_, i) { return value(G, i, m.key); });
    var scores = stats.map(function (s, i) { return score(m.key, s, mine[i]); });
    var scored = scores.map(function (p, i) { return [p, i]; }).filter(function (x) { return x[0] !== null; });
    var ahead = scored.filter(function (x) { return x[0] >= 50; }).length;
    scored.sort(function (a, b) { return b[0] - a[0]; });
    var summary = '<div class="summary">' +
      stat("Peers", grp.peers.length.toLocaleString() + ' <span class="unit">· ' + logged.toLocaleString() + " logged</span>") +
      stat(directional ? "Bosses ahead of half the peers" : "Bosses above half the peers", ahead + '<span class="unit">/' + scored.length + "</span>") +
      (directional && scored.length ? stat("Best boss", esc(names[scored[0][1]]) + ' <span class="unit">' + scored[0][0] + "%</span>") +
        stat("Weakest boss", esc(names[scored[scored.length - 1][1]]) + ' <span class="unit">' + scored[scored.length - 1][0] + "%</span>") : "") +
      "</div>";
    var legend = '<div class="legend"><span><svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="3" style="fill:var(--peer)"></circle></svg>One peer guild</span>' +
      '<span><svg width="22" height="12" aria-hidden="true"><rect y="2" width="22" height="8" rx="2" style="fill:var(--band)"></rect></svg>Middle half of peers</span>' +
      '<span><svg width="6" height="14" aria-hidden="true"><rect x="2" width="2" height="14" style="fill:var(--text)"></rect></svg>Peer median</span>' +
      '<span><svg width="14" height="14" aria-hidden="true"><path d="M7 1 L13 7 L7 13 L1 7Z" style="fill:var(--gb)"></path></svg>' + esc(G.name) + "</span></div>";
    var scoreHead = directional ? "Better than" : "Above";
    var rows = names.map(function (name, i) {
      var s = stats[i], v = mine[i];
      var low = v !== null && m.key === "pulls_to_kill" && s.floor !== undefined && v < s.floor;
      return '<tr><th scope="row">' + esc(name) + '</th><td class="num gb"><b>' + (v === null ? missing(G, i) : esc(m.fmt(v))) +
        (low ? '<span class="muted" title="Under a quarter of the peer median, so the logs may miss nights">*</span>' : "") + "</b></td>" +
        '<td class="num">' + (s.med === undefined ? "–" : esc(m.fmt(s.med))) + "</td>" +
        '<td class="stripcell">' + (s.med === undefined ? '<span class="muted">Fewer than ' + data.raw.min_sample + " peers with this in their numbers</span>" : strip(s, v, m)) + "</td>" +
        '<td class="num">' + s.n + '</td><td class="num">' + scorePill(m.key, scores[i]) + "</td></tr>";
    }).join("");
    var table = '<div class="scroll"><table class="cmp"><thead><tr><th scope="col">Boss</th><th scope="col" class="num">' + esc(G.name) +
      '</th><th scope="col" class="num">Peer median</th><th scope="col">Peers with a kill</th><th scope="col" class="num">Peers</th>' +
      '<th scope="col" class="num">' + scoreHead + "</th></tr></thead><tbody>" + rows + "</tbody></table></div>";
    var note = '<p class="note">' + (directional
      ? scoreHead + " is the share of those peers " + (HIGHER_BETTER[m.key] ? "with a lower value than " : "that needed more than ") + esc(G.name) + "."
      : "Above is the share of those peers with a lower value than " + esc(G.name) + ".") +
      " Peers with under a quarter of the median pull count are left out as incomplete logs, as in the bracket view. Dots past the right edge are clipped to it.</p>";
    return head + pickers + summary + metricPicker(data) + legend + table + note;
  }

  // ---- Entry point, called by app.js ----

  function render(a) {
    api = a;
    var el = $("guild-view"), t = api.tierEntry();
    if (!t || !t.compare) {
      // The site can be deployed ahead of the data: an older snapshot has no compare file yet.
      el.innerHTML = '<section class="panel"><p class="none">' + (t && t.snapshot
        ? "These views fill in after the next daily data refresh."
        : "This tier has no guild data yet.") + "</p></section>";
      return;
    }
    var key = t.key, view = api.state.view;
    if (!el.firstChild || el.getAttribute("data-tier") !== key) {
      el.innerHTML = '<section class="panel"><p class="none">Loading guild data for ' + esc(t.name) + "…</p></section>";
    }
    load(t).then(function (data) {
      if (api.state.view !== view || api.tierEntry().key !== key) return;  // moved on while it loaded
      el.setAttribute("data-tier", key);
      el.innerHTML = '<section class="panel">' + (view === "h2h" ? renderH2H(data) : renderPeers(data)) + "</section>";
      bindSearch(data);
    }).catch(function (err) {
      el.innerHTML = '<section class="panel"><p class="none">Couldn\'t load the guild data. Reload the page to try again.</p></section>';
      if (window.console) console.error(err);
    });
  }

  window.GuildCompare = { render: render };
})();
