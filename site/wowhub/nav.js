/*
 * WoWHub brand kit: nav.js (v1)
 * Injects the shared 48px top bar into any page.
 *
 *   <script src="https://wowhub.net/nav.js" data-app="raids" data-app-name="Raiding Analytics" defer></script>
 *
 * data-app       the app's id from apps.json. Leave it off on the hub.
 * data-app-name  optional; shows the name before apps.json loads.
 *
 * Everything is scoped under .wh-nav / .wh-navmenu and uses its own styles, so it
 * works with or without brand.css and doesn't touch the app's own layout.
 */
(function () {
  'use strict';
  if (window.__whNavLoaded) return;
  window.__whNavLoaded = true;

  var script = document.currentScript;
  var base = script && script.src ? new URL('.', script.src).href : '/';
  var appId = (script && script.getAttribute('data-app')) || '';
  var appNameHint = (script && script.getAttribute('data-app-name')) || '';

  var C = {
    bg: 'var(--wh-surface, #1C1515)',
    raised: 'var(--wh-raised, #251B1B)',
    border: 'var(--wh-border, #3A2B2B)',
    text: 'var(--wh-text, #F0E6E2)',
    muted: 'var(--wh-muted, #B39F9B)',
    accent: 'var(--wh-accent, #E5675C)',
    live: 'var(--wh-live, #7FE0A8)',
    wip: 'var(--wh-wip, #BDB7B4)',
    beta: 'var(--wh-beta, #9CCBFF)'
  };

  var WORDMARK = "<path d=\"M3.7 -69.4H20.0L36.0 -24.200000000000003L30.0 1.8ZM53.7 -71.60000000000001 55.5 -61.7 33.300000000000004 -9.3Q33.300000000000004 -9.3 32.7 -7.6000000000000005Q32.1 -5.9 31.55 -3.4000000000000004Q31.0 -0.9 30.900000000000002 1.8H30.0L27.200000000000003 -10.100000000000001L52.800000000000004 -71.60000000000001ZM53.7 -71.5 75.7 -22.900000000000002 70.9 1.8 46.800000000000004 -51.5ZM92.4 -69.4 73.60000000000001 -9.3Q73.60000000000001 -9.3 73.10000000000001 -7.550000000000001Q72.60000000000001 -5.800000000000001 72.2 -3.2500000000000004Q71.8 -0.7000000000000001 71.9 1.8H70.9L68.10000000000001 -8.1L85.60000000000001 -69.4ZM83.7 -62.800000000000004Q84.5 -65.8 83.2 -67.4Q81.9 -69.0 79.9 -69.0H79.0V-70.0H99.9V-69.0Q99.9 -69.0 99.5 -69.0Q99.10000000000001 -69.0 99.10000000000001 -69.0Q96.80000000000001 -69.0 94.10000000000001 -67.55000000000001Q91.4 -66.10000000000001 90.30000000000001 -62.800000000000004ZM22.5 -62.800000000000004H6.2Q4.9 -66.10000000000001 2.3000000000000003 -67.55000000000001Q-0.30000000000000004 -69.0 -2.6 -69.0Q-2.6 -69.0 -3.0 -69.0Q-3.4000000000000004 -69.0 -3.4000000000000004 -69.0V-70.0H27.1V-69.0H26.200000000000003Q24.3 -69.0 22.85 -67.4Q21.400000000000002 -65.8 22.5 -62.800000000000004Z\" fill=\"currentColor\"/><g transform=\"translate(100.10 -66) scale(2.3571)\"><path d=\"M18.8 2.4 L25.6 9.2 V18.8 L18.8 25.6 H9.2 L2.4 18.8 V9.2 L9.2 2.4 Z\" stroke=\"currentColor\" stroke-width=\"2.2\" stroke-linejoin=\"round\"/><path d=\"M14 5 V11 M14 17 V23 M5 14 H11 M17 14 H23\" stroke=\"currentColor\" stroke-width=\"2.2\" stroke-linecap=\"round\"/><circle cx=\"14\" cy=\"14\" r=\"2.8\" fill=\"currentColor\"/></g><path d=\"M172.8 -69.4H189.10000000000002L205.10000000000002 -24.200000000000003L199.10000000000002 1.8ZM222.8 -71.60000000000001 224.60000000000002 -61.7 202.40000000000003 -9.3Q202.40000000000003 -9.3 201.8 -7.6000000000000005Q201.20000000000002 -5.9 200.65000000000003 -3.4000000000000004Q200.10000000000002 -0.9 200.00000000000003 1.8H199.10000000000002L196.3 -10.100000000000001L221.90000000000003 -71.60000000000001ZM222.8 -71.5 244.8 -22.900000000000002 240.00000000000003 1.8 215.90000000000003 -51.5ZM261.5 -69.4 242.70000000000005 -9.3Q242.70000000000005 -9.3 242.20000000000005 -7.550000000000001Q241.70000000000005 -5.800000000000001 241.30000000000004 -3.2500000000000004Q240.90000000000003 -0.7000000000000001 241.00000000000003 1.8H240.00000000000003L237.20000000000005 -8.1L254.70000000000005 -69.4ZM252.8 -62.800000000000004Q253.60000000000002 -65.8 252.3 -67.4Q251.00000000000003 -69.0 249.00000000000003 -69.0H248.10000000000002V-70.0H269.0V-69.0Q269.0 -69.0 268.6 -69.0Q268.20000000000005 -69.0 268.20000000000005 -69.0Q265.90000000000003 -69.0 263.20000000000005 -67.55000000000001Q260.5 -66.10000000000001 259.40000000000003 -62.800000000000004ZM191.60000000000002 -62.800000000000004H175.3Q174.00000000000003 -66.10000000000001 171.40000000000003 -67.55000000000001Q168.8 -69.0 166.50000000000003 -69.0Q166.50000000000003 -69.0 166.10000000000002 -69.0Q165.70000000000002 -69.0 165.70000000000002 -69.0V-70.0H196.20000000000002V-69.0H195.3Q193.40000000000003 -69.0 191.95000000000005 -67.4Q190.50000000000003 -65.8 191.60000000000002 -62.800000000000004Z\" fill=\"currentColor\"/><path d=\"M340.50000000000006 -70.0V0.0H325.50000000000006V-70.0ZM293.1 -70.0V0.0H278.1V-70.0ZM326.40000000000003 -37.0V-32.7H292.1V-37.0ZM278.40000000000003 -7.300000000000001V0.0H270.40000000000003V-1.0Q270.40000000000003 -1.0 271.05000000000007 -1.0Q271.70000000000005 -1.0 271.70000000000005 -1.0Q274.30000000000007 -1.0 276.1500000000001 -2.85Q278.00000000000006 -4.7 278.1 -7.300000000000001ZM278.40000000000003 -62.7H278.1Q278.00000000000006 -65.3 276.1500000000001 -67.15Q274.30000000000007 -69.0 271.70000000000005 -69.0Q271.70000000000005 -69.0 271.05000000000007 -69.0Q270.40000000000003 -69.0 270.40000000000003 -69.0V-70.0H278.40000000000003ZM292.80000000000007 -7.300000000000001H293.1Q293.20000000000005 -4.7 295.05000000000007 -2.85Q296.90000000000003 -1.0 299.50000000000006 -1.0Q299.50000000000006 -1.0 300.1 -1.0Q300.70000000000005 -1.0 300.80000000000007 -1.0V0.0H292.80000000000007ZM292.80000000000007 -62.7V-70.0H300.80000000000007V-69.0Q300.70000000000005 -69.0 300.1 -69.0Q299.50000000000006 -69.0 299.50000000000006 -69.0Q296.90000000000003 -69.0 295.05000000000007 -67.15Q293.20000000000005 -65.3 293.1 -62.7ZM325.80000000000007 -7.300000000000001V0.0H317.80000000000007V-1.0Q317.90000000000003 -1.0 318.5 -1.0Q319.1 -1.0 319.1 -1.0Q321.70000000000005 -1.0 323.6 -2.85Q325.50000000000006 -4.7 325.50000000000006 -7.300000000000001ZM325.80000000000007 -62.7H325.50000000000006Q325.50000000000006 -65.3 323.6 -67.15Q321.70000000000005 -69.0 319.1 -69.0Q319.1 -69.0 318.5 -69.0Q317.90000000000003 -69.0 317.80000000000007 -69.0V-70.0H325.80000000000007ZM340.20000000000005 -7.300000000000001H340.50000000000006Q340.6 -4.7 342.45000000000005 -2.85Q344.30000000000007 -1.0 346.90000000000003 -1.0Q346.90000000000003 -1.0 347.55000000000007 -1.0Q348.20000000000005 -1.0 348.20000000000005 -1.0V0.0H340.20000000000005ZM340.20000000000005 -62.7V-70.0H348.20000000000005V-69.0Q348.20000000000005 -69.0 347.55000000000007 -69.0Q346.90000000000003 -69.0 346.90000000000003 -69.0Q344.30000000000007 -69.0 342.45000000000005 -67.15Q340.6 -65.3 340.50000000000006 -62.7Z\" style=\"fill:var(--wh-logo-text,#F0E6E2)\"/><path d=\"M375.50000000000006 -60.0V-22.3Q375.50000000000006 -13.100000000000001 379.75000000000006 -7.9Q384.00000000000006 -2.7 391.6 -2.7Q399.50000000000006 -2.7 403.85 -7.6Q408.20000000000005 -12.5 408.30000000000007 -21.200000000000003V-60.0H414.90000000000003V-21.8Q414.90000000000003 -11.100000000000001 408.35 -4.9Q401.80000000000007 1.3 389.8 1.3Q375.3 1.3 368.20000000000005 -4.85Q361.1 -11.0 361.1 -21.700000000000003V-60.0ZM361.3 -60.0V-54.800000000000004H361.1Q361.00000000000006 -56.7 359.70000000000005 -57.900000000000006Q358.40000000000003 -59.1 356.50000000000006 -59.1Q356.50000000000006 -59.1 355.80000000000007 -59.1Q355.1 -59.1 355.1 -59.1V-60.0ZM381.40000000000003 -60.0V-59.1Q381.40000000000003 -59.1 380.70000000000005 -59.1Q380.00000000000006 -59.1 380.00000000000006 -59.1Q378.1 -59.1 376.80000000000007 -57.900000000000006Q375.50000000000006 -56.7 375.50000000000006 -54.800000000000004H375.3V-60.0ZM408.50000000000006 -60.0V-54.800000000000004H408.30000000000007Q408.20000000000005 -56.7 406.90000000000003 -57.900000000000006Q405.6 -59.1 403.80000000000007 -59.1Q403.80000000000007 -59.1 403.1 -59.1Q402.40000000000003 -59.1 402.40000000000003 -59.1V-60.0ZM420.80000000000007 -60.0V-59.1Q420.80000000000007 -59.1 420.1500000000001 -59.1Q419.50000000000006 -59.1 419.50000000000006 -59.1Q417.6 -59.1 416.25 -57.900000000000006Q414.90000000000003 -56.7 414.90000000000003 -54.800000000000004H414.70000000000005V-60.0Z\" style=\"fill:var(--wh-logo-text,#F0E6E2)\"/><path d=\"M436.8 -60.0H453.40000000000003Q457.3 -60.0 461.30000000000007 -59.400000000000006Q465.30000000000007 -58.800000000000004 468.6 -57.2Q471.90000000000003 -55.6 473.90000000000003 -52.7Q475.90000000000003 -49.800000000000004 475.90000000000003 -45.1Q475.90000000000003 -41.300000000000004 474.30000000000007 -38.6Q472.70000000000005 -35.9 470.20000000000005 -34.4Q467.70000000000005 -32.9 464.90000000000003 -32.7Q469.30000000000007 -32.4 472.80000000000007 -30.4Q476.30000000000007 -28.400000000000002 478.45000000000005 -25.050000000000004Q480.6 -21.700000000000003 480.6 -17.1Q480.6 -12.4 478.6 -9.15Q476.6 -5.9 473.1 -3.85Q469.6 -1.8 465.05000000000007 -0.9Q460.50000000000006 0.0 455.50000000000006 0.0H446.50000000000006Q446.50000000000006 0.0 446.50000000000006 -1.0Q446.50000000000006 -2.0 446.50000000000006 -3.0Q446.50000000000006 -4.0 446.50000000000006 -4.0H451.3Q454.90000000000003 -4.0 457.85 -5.35Q460.8 -6.7 462.6 -9.8Q464.40000000000003 -12.9 464.40000000000003 -18.0Q464.40000000000003 -21.5 463.35 -24.15Q462.30000000000007 -26.8 460.4000000000001 -28.450000000000003Q458.50000000000006 -30.1 455.90000000000003 -30.900000000000002Q453.3 -31.700000000000003 450.20000000000005 -31.700000000000003V-32.6Q452.40000000000003 -32.6 454.40000000000003 -33.25Q456.40000000000003 -33.9 457.85 -35.25Q459.3 -36.6 460.15000000000003 -38.8Q461.00000000000006 -41.0 461.00000000000006 -44.1Q461.00000000000006 -50.800000000000004 457.90000000000003 -53.45Q454.8 -56.1 450.1 -56.1H437.70000000000005Q437.70000000000005 -56.2 437.45000000000005 -57.150000000000006Q437.20000000000005 -58.1 437.0 -59.05Q436.8 -60.0 436.8 -60.0ZM447.20000000000005 -60.0V0.0H433.00000000000006V-60.0ZM433.3 -6.300000000000001V0.0H426.50000000000006V-1.0Q426.6 -1.0 427.05000000000007 -1.0Q427.50000000000006 -1.0 427.6 -1.0Q430.00000000000006 -1.0 431.55000000000007 -2.5500000000000003Q433.1 -4.1000000000000005 433.00000000000006 -6.300000000000001ZM433.3 -53.7H433.00000000000006Q433.1 -56.1 431.55000000000007 -57.55Q430.00000000000006 -59.0 427.6 -59.0Q427.50000000000006 -59.0 427.05000000000007 -59.0Q426.6 -59.0 426.50000000000006 -59.0V-60.0H433.3Z\" style=\"fill:var(--wh-logo-text,#F0E6E2)\"/>";
  var ICON = "<path d=\"M18.8 2.4 L25.6 9.2 V18.8 L18.8 25.6 H9.2 L2.4 18.8 V9.2 L9.2 2.4 Z\" stroke=\"currentColor\" stroke-width=\"1.2\" stroke-linejoin=\"round\"/><path d=\"M14 5 V11 M14 17 V23 M5 14 H11 M17 14 H23\" stroke=\"currentColor\" stroke-width=\"1.3\" stroke-linecap=\"round\"/><circle cx=\"14\" cy=\"14\" r=\"2.8\" fill=\"currentColor\"/>";
  var GRID_ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>';
  var CHEVRON = '<svg class="wh-chev" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
  var CHECK = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>';

  var css = [
    '.wh-nav,.wh-nav *,.wh-navmenu,.wh-navmenu *{box-sizing:border-box}',
    '.wh-nav{all:initial;box-sizing:border-box;display:block;position:relative;z-index:2147483000;height:48px;background:' + C.bg + ';border-bottom:1px solid ' + C.border + ';color:' + C.text + ';font:400 14px/1.4 var(--wh-font-body,Inter,system-ui,-apple-system,"Segoe UI",sans-serif);-webkit-font-smoothing:antialiased}',
    '.wh-nav__inner{height:47px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 8px 0 16px;max-width:var(--wh-nav-max,none);margin:0 auto}',
    '.wh-nav__left{display:flex;align-items:center;gap:10px;min-width:0}',
    '.wh-nav__home{display:inline-flex;align-items:center;gap:8px;min-height:44px;color:' + C.text + ';text-decoration:none;flex:0 0 auto}',
    '.wh-nav__home:focus-visible,.wh-nav__btn:focus-visible,.wh-navmenu a:focus-visible{outline:2px solid ' + C.accent + ';outline-offset:2px;border-radius:6px}',
    '.wh-nav__icon{color:' + C.accent + '}',
    '.wh-nav__word{display:block;height:18px;width:auto;color:' + C.accent + ';--wh-logo-text:' + C.text + '}',
    '.wh-nav__icon{display:none}',
    '.wh-nav__sep{color:' + C.border + ';font-size:18px;flex:0 0 auto}',
    '.wh-nav__app{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}',
    '.wh-nav__btn{display:inline-flex;align-items:center;gap:8px;min-height:36px;padding:0 12px;margin:0;border-radius:8px;border:1px solid ' + C.border + ';background:transparent;color:' + C.text + ';font-size:13px;font-weight:500;line-height:1;font-family:inherit;cursor:pointer}',
    '.wh-nav__btn:hover{border-color:' + C.muted + '}',
    '.wh-nav__btn[aria-expanded="true"]{border-color:' + C.accent + ';background:' + C.raised + '}',
    '.wh-nav__btn[aria-expanded="true"] .wh-chev{transform:rotate(180deg)}',
    '.wh-navmenu{position:absolute;top:52px;right:8px;width:360px;max-width:calc(100vw - 16px);background:' + C.bg + ';border:1px solid ' + C.border + ';border-radius:12px;box-shadow:0 18px 40px rgba(0,0,0,.5);overflow:hidden;z-index:2147483001;color:' + C.text + ';font:400 14px/1.4 var(--wh-font-body,Inter,system-ui,sans-serif)}',
    '.wh-navmenu[hidden]{display:none}',
    '.wh-navmenu ul{list-style:none;margin:0;padding:6px}',
    '.wh-navmenu__item{display:flex;align-items:center;gap:12px;padding:10px;border-radius:8px;color:' + C.text + ';text-decoration:none;min-height:56px}',
    'a.wh-navmenu__item:hover{background:' + C.raised + '}',
    '.wh-navmenu__item[aria-current="page"]{background:' + C.raised + '}',
    '.wh-navmenu__item--wip{opacity:.75}',
    '.wh-navmenu__icon{width:36px;height:36px;flex:0 0 36px;border-radius:8px;background:' + C.raised + ';display:inline-flex;align-items:center;justify-content:center;color:' + C.accent + '}',
    '.wh-navmenu__text{display:flex;flex-direction:column;gap:2px;flex:1 1 auto;min-width:0}',
    '.wh-navmenu__name{font-weight:600;font-size:14px}',
    '.wh-navmenu__short{font-size:12px;color:' + C.muted + '}',
    '.wh-navmenu__tag{font-size:10px;font-weight:600;letter-spacing:.06em}',
    '.wh-navmenu__tag--live{color:' + C.live + '}.wh-navmenu__tag--wip{color:' + C.wip + '}.wh-navmenu__tag--beta{color:' + C.beta + '}',
    '.wh-navmenu__check{color:' + C.accent + '}',
    '.wh-navmenu__foot{border-top:1px solid ' + C.border + ';padding:12px 16px;display:flex;flex-direction:column;gap:8px}',
    '.wh-navmenu__all{font-size:13px;font-weight:500;color:' + C.accent + ';text-decoration:none}',
    '.wh-navmenu__legal{font-size:11px;line-height:1.5;color:' + C.muted + '}',
    '.wh-navbackdrop{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:2147482999}',
    '.wh-navbackdrop[hidden]{display:none}',
    '@media (max-width:639px){',
    '  .wh-nav__btn .wh-nav__btnlabel,.wh-nav__btn .wh-chev{display:none}',
    '  .wh-nav__btn{border:0;width:44px;height:44px;padding:0;justify-content:center}',
    '  .wh-nav--inapp .wh-nav__word{display:none}',
    '  .wh-nav--inapp .wh-nav__icon{display:block}',
    '  .wh-navmenu{position:fixed;top:auto;left:0;right:0;bottom:0;width:auto;max-width:none;border-radius:16px 16px 0 0;border-bottom:0;max-height:85vh;overflow-y:auto;padding-bottom:env(safe-area-inset-bottom)}',
    '  .wh-navmenu::before{content:"";display:block;width:40px;height:4px;border-radius:2px;background:' + C.border + ';margin:10px auto 4px}',
    '}'
  ].join('\n');

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function svgIcon(inner, size) {
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + inner + '</svg>';
  }

  function ensureFonts() {
    var links = document.querySelectorAll('link[href*="fonts.googleapis.com"]');
    for (var i = 0; i < links.length; i++) if (/Inter/.test(links[i].href)) return;
    var l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap';
    document.head.appendChild(l);
  }

  function mount() {
    ensureFonts();
    var style = el('style');
    style.setAttribute('data-wh-nav', '');
    style.textContent = css;
    document.head.appendChild(style);

    var hubUrl = 'https://wowhub.net/';  // vendored copy: the hub stays on wowhub.net
    var nav = el('header', 'wh-nav' + (appId ? ' wh-nav--inapp' : ''));
    nav.setAttribute('role', 'banner');
    var inner = el('div', 'wh-nav__inner');
    var left = el('div', 'wh-nav__left');
    var home = el('a', 'wh-nav__home',
      '<svg class="wh-nav__icon" width="24" height="24" viewBox="0 0 28 28" fill="none" aria-hidden="true">' + ICON + '</svg>' +
      '<svg class="wh-nav__word" viewBox="-2 -73.6 487.3 77.6" fill="none" aria-hidden="true">' + WORDMARK + '</svg>');
    home.href = hubUrl;
    home.setAttribute('aria-label', 'WoWHub home');
    left.appendChild(home);
    var appLabel = null;
    if (appId) {
      left.appendChild(el('span', 'wh-nav__sep', '/')).setAttribute('aria-hidden', 'true');
      appLabel = el('span', 'wh-nav__app');
      appLabel.textContent = appNameHint;
      left.appendChild(appLabel);
    }
    var btn = el('button', 'wh-nav__btn', GRID_ICON + '<span class="wh-nav__btnlabel">Apps</span>' + CHEVRON);
    btn.type = 'button';
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-controls', 'wh-navmenu');
    btn.setAttribute('aria-label', 'Switch app');
    inner.appendChild(left);
    inner.appendChild(btn);
    nav.appendChild(inner);

    var backdrop = el('div', 'wh-navbackdrop');
    backdrop.hidden = true;
    var menu = el('div', 'wh-navmenu');
    menu.id = 'wh-navmenu';
    menu.hidden = true;
    menu.setAttribute('role', 'dialog');
    menu.setAttribute('aria-label', 'WoWHub apps');
    menu.innerHTML = '<ul><li class="wh-navmenu__short" style="padding:12px">Loading apps…</li></ul>';
    var foot = el('div', 'wh-navmenu__foot',
      '<a class="wh-navmenu__all" href="' + esc(hubUrl) + '">All apps on wowhub.net →</a>' +
      '<span class="wh-navmenu__legal">Fan project. Not affiliated with Blizzard Entertainment.</span>');
    menu.appendChild(foot);
    nav.appendChild(menu);

    document.body.insertBefore(backdrop, document.body.firstChild);
    document.body.insertBefore(nav, document.body.firstChild);

    function isMobile() { return window.matchMedia('(max-width: 639px)').matches; }
    function open() {
      menu.hidden = false;
      backdrop.hidden = !isMobile();
      btn.setAttribute('aria-expanded', 'true');
      var first = menu.querySelector('a');
      if (first) first.focus({ preventScroll: true });
    }
    function close(returnFocus) {
      if (menu.hidden) return;
      menu.hidden = true;
      backdrop.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      if (returnFocus) btn.focus();
    }
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (menu.hidden) open(); else close(false);
    });
    backdrop.addEventListener('click', function () { close(true); });
    document.addEventListener('click', function (e) {
      if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) close(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !menu.hidden) close(true);
    });

    fetch(new URL('apps.json', base).href, { credentials: 'omit' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        var apps = (data && data.apps) || [];
        var ul = el('ul');
        apps.forEach(function (a) {
          var current = a.id === appId;
          var isLive = a.status === 'live' || a.status === 'beta';
          var li = el('li');
          var item = el(isLive ? 'a' : 'div', 'wh-navmenu__item' + (isLive ? '' : ' wh-navmenu__item--wip'));
          if (isLive) item.href = a.url;
          if (current) item.setAttribute('aria-current', 'page');
          var right = current
            ? '<span class="wh-navmenu__check">' + CHECK + '</span>'
            : '<span class="wh-navmenu__tag wh-navmenu__tag--' + esc(a.status) + '">' + esc(String(a.status).toUpperCase()) + '</span>';
          item.innerHTML =
            '<span class="wh-navmenu__icon">' + svgIcon(a.icon || '', 20) + '</span>' +
            '<span class="wh-navmenu__text"><span class="wh-navmenu__name">' + esc(a.name) + '</span>' +
            '<span class="wh-navmenu__short">' + esc(current ? 'You are here' : (isLive ? a.short : 'Coming soon')) + '</span></span>' + right;
          li.appendChild(item);
          ul.appendChild(li);
          if (current && appLabel) appLabel.textContent = a.name;
        });
        menu.replaceChild(ul, menu.firstChild);
      })
      .catch(function () {
        menu.firstChild.innerHTML = '<li class="wh-navmenu__short" style="padding:12px">Couldn’t load the app list.</li>';
      });
  }

  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount);
})();
