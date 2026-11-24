/* 面板主题同步（SPEC：深色模式）
 *
 * 面板是独立 iframe 文档，宿主的 theme.css 够不到它们。
 * 这个共享脚本做两件事：
 *   1. 定义亮/暗两套 --wm-* 令牌，按当前主题写进面板的 :root；
 *   2. 监听宿主的 host.theme 事件（宿主在系统主题变化时广播），
 *      以及自身的 prefers-color-scheme 变化，随时切换。
 *
 * 面板接入方式（一行）：
 *   <script src="/minimal/assets/theme-sync.js"></script>
 * 面板 CSS 无需改动：var(--wm-x, 回退值) 的回退只在令牌缺失时生效，
 * 令牌一旦由本脚本写入，所有面板颜色自动跟随主题。
 */
(function () {
  'use strict';

  var LIGHT = {
    '--wm-bl-0': '#ffffff', '--wm-bl-50': '#fdfdfd', '--wm-bl-100': '#f8f8f9',
    '--wm-bl-150': '#f3f3f5', '--wm-bl-200': '#ededee', '--wm-bl-300': '#d9d9dc',
    '--wm-bl-400': '#b8b8bc', '--wm-bl-500': '#8c8c90', '--wm-bl-600': '#6a6a6a',
    '--wm-bl-700': '#4f4f52', '--wm-bl-800': '#2e2e31', '--wm-bl-900': '#1b1b1e',
    '--wm-ink': '#16191d', '--wm-ink-soft': '#2f3841', '--wm-ink-weak': '#e9edf1',
    '--wm-bg-base': '#ffffff', '--wm-bg-sidebar': '#f8f8f9', '--wm-bg-panel': '#ffffff',
    '--wm-bg-input': '#f3f3f5', '--wm-bg-hover': '#f3f3f5',
    '--wm-bg-active': 'rgba(0, 0, 0, 0.08)',
    '--wm-label': 'rgba(0, 0, 0, 0.80)', '--wm-label-2nd': 'rgba(0, 0, 0, 0.60)',
    '--wm-label-dim': '#6a6a6a',
    '--wm-border': 'rgba(16, 26, 39, 0.08)', '--wm-border-soft': 'rgba(16, 26, 39, 0.05)',
    '--wm-accent': '#16191d', '--wm-accent-hi': '#2f3841', '--wm-accent-weak': '#e9edf1',
    '--wm-on-accent': '#ffffff',
    '--wm-user-bubble': '#f3f3f5',
    '--wm-shadow-sm': '0 2px 4px rgba(16, 26, 39, 0.055)',
    '--wm-shadow': '0 4px 8px rgba(16, 26, 39, 0.07)',
    'color-scheme': 'light dark',
  };

  var DARK = {
    '--wm-bl-0': '#1b1b1e', '--wm-bl-50': '#202023', '--wm-bl-100': '#26262a',
    '--wm-bl-150': '#2e2e33', '--wm-bl-200': '#3a3a40', '--wm-bl-300': '#4a4a51',
    '--wm-bl-400': '#6a6a72', '--wm-bl-500': '#8e8e96', '--wm-bl-600': '#a8a8b0',
    '--wm-bl-700': '#c2c2c8', '--wm-bl-800': '#dddee2', '--wm-bl-900': '#ececEE',
    '--wm-ink': '#e8eaee', '--wm-ink-soft': '#c9cdd4', '--wm-ink-weak': '#2a3440',
    '--wm-bg-base': '#1b1b1e', '--wm-bg-sidebar': '#26262a', '--wm-bg-panel': '#1b1b1e',
    '--wm-bg-input': '#2e2e33', '--wm-bg-hover': '#2e2e33',
    '--wm-bg-active': 'rgba(255, 255, 255, 0.10)',
    '--wm-label': 'rgba(255, 255, 255, 0.82)', '--wm-label-2nd': 'rgba(255, 255, 255, 0.62)',
    '--wm-label-dim': '#9a9aa2',
    '--wm-border': 'rgba(235, 238, 245, 0.14)', '--wm-border-soft': 'rgba(235, 238, 245, 0.08)',
    '--wm-accent': '#e8eaee', '--wm-accent-hi': '#c9cdd4', '--wm-accent-weak': '#2a3440',
    '--wm-on-accent': '#16191d',
    '--wm-user-bubble': '#2e2e33',
    '--wm-shadow-sm': '0 2px 4px rgba(0, 0, 0, 0.4)',
    '--wm-shadow': '0 4px 8px rgba(0, 0, 0, 0.5)',
    'color-scheme': 'dark',
  };

  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  // 宿主明确广播过的主题优先；没广播过跟随系统。
  var fromHost = null;

  function applyTokens(theme) {
    var tokens = theme === 'dark' ? DARK : LIGHT;
    Object.keys(tokens).forEach(function (k) {
      if (k === 'color-scheme') {
        root.style.colorScheme = tokens[k];
      } else {
        root.style.setProperty(k, tokens[k]);
      }
    });
    root.dataset.theme = theme;
  }

  function current() {
    if (fromHost) return fromHost;
    return mq && mq.matches ? 'dark' : 'light';
  }

  function refresh() { applyTokens(current()); }

  // 宿主广播：{ type:'event', event:'host.theme', data:{ dark:boolean } }
  window.addEventListener('message', function (m) {
    var d = m.data;
    if (d && d.type === 'event' && d.event === 'host.theme' && d.data) {
      fromHost = d.data.dark ? 'dark' : 'light';
      refresh();
    }
  });

  if (mq) {
    // 旧引擎 MediaQueryList 只有 addListener；新引擎用 addEventListener('change', …)
    if (mq.addEventListener) mq.addEventListener('change', refresh);
    else if (mq.addListener) mq.addListener(refresh);
  }

  refresh();
})();
