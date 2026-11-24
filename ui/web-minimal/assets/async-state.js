/* purrcat:async-state:spec */
/**
 * 面板异步状态：一份词表，前端与后端读同一份。
 *
 * 状态不是一张扁平的枚举，而是三件正交的事分别说清楚：
 *   data    —— 有哪些数据（none / partial / stale / complete）
 *   request —— 请求正在做什么（idle / first_load / refresh / submitting / …）
 *   result  —— 业务结果是什么（ok / empty / failed / unavailable）
 *
 * 三者组合出最终呈现。服务端知道 data 与 result，客户端知道 request，
 * 规则表跟词表放在一起，两边不会各自漂移。
 *
 * 注意：这套状态只说「界面现在处于什么状态」，从不说「这个结论是对的」。
 * 科学验证由 acceptance / verification 那套词表负责，两层互不冒充。
 */
var PurrCatAsyncSpec = {
  "version": 1,
  "data": ["none", "partial", "stale", "complete"],
  "request": [
    "idle",
    "first_load",
    "refresh",
    "submitting",
    "cancelling",
    "cancelled",
    "completed"
  ],
  "result": ["pending", "ok", "empty", "failed", "unavailable"],
  "state": [
    "first_load",
    "refreshing",
    "submitting",
    "cancelling",
    "cancelled",
    "completed",
    "first_load_failed",
    "refresh_failed",
    "refresh_unavailable",
    "ready",
    "empty",
    "partial",
    "stale",
    "unavailable"
  ],
  "reason": [
    "no_data",
    "filter_no_match",
    "task_pending",
    "source_missing",
    "source_changed",
    "permission",
    "prerequisite",
    "not_found",
    "conflict",
    "parse",
    "io",
    "server"
  ],
  "action": [
    "none",
    "retry",
    "import",
    "adjust_filter",
    "start_task",
    "grant_permission",
    "open_settings"
  ],
  "rules": [
    { "request": "submitting", "state": "submitting" },
    { "request": "cancelling", "state": "cancelling" },
    { "request": "cancelled", "state": "cancelled" },
    { "request": "completed", "state": "completed" },
    { "request": "first_load", "result": "pending", "state": "first_load" },
    { "request": "refresh", "result": "pending", "state": "refreshing" },
    { "result": "empty", "state": "empty" },
    { "result": "unavailable", "data": "none", "state": "unavailable" },
    { "result": "unavailable", "state": "refresh_unavailable" },
    { "result": "failed", "data": "none", "state": "first_load_failed" },
    { "result": "failed", "state": "refresh_failed" },
    { "data": "partial", "state": "partial" },
    { "data": "stale", "state": "stale" },
    { "data": "none", "state": "empty" },
    { "state": "ready" }
  ]
};
/* purrcat:async-state:spec:end */

(function (global) {
  'use strict';

  var SPEC = PurrCatAsyncSpec;

  // ---------- 状态推导 ----------

  /** 三轴组合成最终状态；规则表按顺序命中第一条。 */
  function derive(data, request, result) {
    var d = SPEC.data.indexOf(data) >= 0 ? data : 'complete';
    var q = SPEC.request.indexOf(request) >= 0 ? request : 'idle';
    var r = SPEC.result.indexOf(result) >= 0 ? result : 'ok';
    for (var i = 0; i < SPEC.rules.length; i++) {
      var rule = SPEC.rules[i];
      if (rule.data !== undefined && rule.data !== d) continue;
      if (rule.request !== undefined && rule.request !== q) continue;
      if (rule.result !== undefined && rule.result !== r) continue;
      return rule.state;
    }
    return 'ready';
  }

  // ---------- 文案 ----------

  var EMPTY_TEXT = {
    no_data: {
      title: '还没有数据',
      detail: '这里还没有任何记录。',
      action: 'import',
    },
    filter_no_match: {
      title: '没有匹配的结果',
      detail: '当前的筛选条件没有命中任何记录。',
      action: 'adjust_filter',
    },
    task_pending: {
      title: '任务还没产出结果',
      detail: '这项任务仍在进行，结果出来前这里不会有内容。',
      action: 'start_task',
    },
  };

  var UNAVAILABLE_TEXT = {
    source_missing: {
      title: '原文件已丢失',
      detail: '原件不在了，不会用旧数据代替。重新导入一份再继续。',
      action: 'import',
    },
    source_changed: {
      title: '原文件已变化',
      detail: '原件和当初导入时不一样了，重新导入才能读到现在的内容。',
      action: 'import',
    },
    permission: {
      title: '没有权限',
      detail: '当前身份读不了这个对象。',
      action: 'grant_permission',
    },
    prerequisite: {
      title: '还差前置条件',
      detail: '这个操作要先满足上面的条件才能继续。',
      action: 'open_settings',
    },
    not_found: {
      title: '对象不存在',
      detail: '它可能已经被删掉了。',
      action: 'none',
    },
  };

  var FAILED_TEXT = {
    parse: '内容读不出来',
    io: '读取失败',
    server: '服务出错了',
    conflict: '和当前内容对不上',
    permission: '没有权限',
    not_found: '对象不存在',
  };

  var ACTION_LABEL = {
    retry: '重试',
    import: '导入',
    adjust_filter: '调整筛选',
    start_task: '开始任务',
    grant_permission: '去授权',
    open_settings: '去设置',
    none: '',
  };

  function esc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  // ---------- 文案选择 ----------

  function emptyText(status) {
    var known = EMPTY_TEXT[status && status.reason] || EMPTY_TEXT.no_data;
    return {
      title: known.title,
      detail: (status && status.detail) || known.detail,
      action: known.action,
    };
  }

  function unavailableText(status) {
    var known = UNAVAILABLE_TEXT[status && status.reason] || {
      title: '暂时用不了',
      detail: '',
      action: 'none',
    };
    return {
      title: known.title,
      detail: (status && status.detail) || known.detail,
      action: known.action,
    };
  }

  function failedText(status) {
    var title = FAILED_TEXT[status && status.reason] || '读取失败';
    return { title: title, detail: (status && status.detail) || '', action: 'retry' };
  }

  /** 空 / 失败 / 不可用三类都走整块视图，各自挑文案与下一步。 */
  function blockText(state, status) {
    if (state === 'empty') return emptyText(status);
    if (state === 'unavailable') return unavailableText(status);
    return failedText(status);
  }

  function bannerText(state, status) {
    var detail = (status && status.detail) || '';
    switch (state) {
      case 'refreshing':
        return '更新中…';
      case 'stale':
        return detail || '这份内容已经过期';
      case 'partial':
        return detail || '只有一部分内容可用';
      case 'refresh_failed':
        return detail || '刷新失败，下面还是上一次的结果';
      case 'refresh_unavailable':
        return detail || '来源已经取不到了，下面还是上一次的结果';
      case 'submitting':
        return detail || '处理中…';
      case 'cancelling':
        return '取消中…';
      case 'cancelled':
        return detail || '已取消';
      case 'completed':
        return detail || '已完成';
      default:
        return detail || '';
    }
  }

  // ---------- 渲染 ----------

  function skeletonHtml() {
    return (
      '<div class="pcx-skeleton" aria-hidden="true">' +
      '<span class="pcx-skeleton__line"></span>' +
      '<span class="pcx-skeleton__line"></span>' +
      '<span class="pcx-skeleton__line pcx-skeleton__line--short"></span>' +
      '</div>'
    );
  }

  function blockHtml(state, status) {
    var text = blockText(state, status);
    var html = '<div class="pcx-state pcx-state--' + esc(state) + '" role="status">';
    html += '<div class="pcx-state__title">' + esc(text.title) + '</div>';
    if (text.detail) {
      html += '<div class="pcx-state__detail">' + esc(text.detail) + '</div>';
    }
    if (text.action && text.action !== 'none' && status && status.onAction) {
      html +=
        '<button class="pcx-state__action" data-pcx-action="' +
        esc(text.action) +
        '">' +
        esc(ACTION_LABEL[text.action] || '') +
        '</button>';
    }
    html += '</div>';
    return html;
  }

  /**
   * 一个区域（列表、正文、检查结果……）的状态机。
   *
   * 关键约定：
   *  - 刷新失败保留上一次的内容，并说明那不是最新结果；
   *  - 刷新中不换掉已有内容，只在顶上挂一条提示；
   *  - 空态按原因给不同的下一步，不复用同一个空壳；
   *  - 骨架屏只画灰色块，不伪造数值。
   */
  function Region(node) {
    this.node = node;
    this.hasContent = false;
    this.pending = null;
  }

  /**
   * 换一个对象看：旧内容必须清掉。
   *
   * 刷新同一个对象时保留旧内容（刷新失败还能看上次结果），
   * 但换对象时留着旧内容就是「把旧对象的数据冒充成新对象的」。
   */
  Region.prototype.reset = function () {
    this.node.removeAttribute('aria-busy');
    if (this.pending && this.pending.parentNode) {
      this.pending.parentNode.removeChild(this.pending);
    }
    this.pending = null;
    this.hasContent = false;
    this.node.innerHTML = '';
  };

  Region.prototype.begin = function (request) {
    this.node.setAttribute('aria-busy', 'true');
    var phase = request === 'refresh' && this.hasContent ? 'refresh' : 'first_load';
    if (phase === 'refresh') {
      this.pending = el('div', 'pcx-banner pcx-banner--refreshing', bannerText('refreshing'));
      this.node.insertBefore(this.pending, this.node.firstChild);
    } else {
      this.node.innerHTML =
        '<div class="pcx-skeleton-wrap" role="status" aria-label="载入中">' + skeletonHtml() + '</div>';
    }
    return phase;
  };

  /**
   * 推状态。
   *
   * ``status.data`` 由客户端给——客户端才知道屏幕上现在有没有内容。
   * 服务端只负责业务结果（result）与原因（reason）。
   */

  /** 用客户端的 data 与服务端的 result 推出状态。 */
  Region.prototype.settle = function (status, renderContent) {
    this.node.removeAttribute('aria-busy');
    if (this.pending && this.pending.parentNode) {
      this.pending.parentNode.removeChild(this.pending);
    }
    this.pending = null;

    var request = status.request || 'idle';
    var result = status.result || 'ok';
    var state = status.state || derive(status.data, request, result);

    if (state === 'ready' || state === 'partial' || state === 'stale' || state === 'completed') {
      this.hasContent = true;
      if (renderContent) renderContent(this.node);
      if (state === 'partial' || state === 'stale') {
        this.node.insertBefore(
          el('div', 'pcx-banner pcx-banner--' + state, bannerText(state, status)),
          this.node.firstChild,
        );
      }
      return state;
    }

    if (state === 'refresh_failed' || state === 'refresh_unavailable') {
      // 旧内容留着，但要说明那不是最新结果。
      var banner = el(
        'div',
        'pcx-banner pcx-banner--' + state,
        bannerText(state, status),
      );
      if (status.onAction) {
        var action = status.action || 'retry';
        var act = el('button', 'pcx-banner__action', ACTION_LABEL[action] || '重试');
        act.onclick = function () {
          status.onAction(action);
        };
        banner.appendChild(act);
      }
      this.node.insertBefore(banner, this.node.firstChild);
      return state;
    }

    this.hasContent = false;
    this.node.innerHTML = blockHtml(state, status);
    var actionBtn = this.node.querySelector('[data-pcx-action]');
    if (actionBtn && status.onAction) {
      actionBtn.onclick = function () {
        status.onAction(actionBtn.getAttribute('data-pcx-action'));
      };
    }
    return state;
  };

  /**
   * 请求失败。服务端给了 status 就用它（能分清「不可用」和「失败」），
   * 没给就退回到「读取失败」。
   */
  Region.prototype.fail = function (err, onRetry) {
    var server = err && err.status;
    // 屏幕上有内容就说明这是刷新失败——旧内容留着，只是标明不是最新结果。
    var payload = {
      data: this.hasContent ? 'complete' : 'none',
      request: 'idle',
      result: 'failed',
      reason: 'server',
      detail: (err && err.message) || '读取失败',
      onAction: onRetry,
    };
    if (server) {
      if (server.result) payload.result = server.result;
      if (server.reason) payload.reason = server.reason;
      if (server.detail) payload.detail = server.detail;
      if (server.action) payload.action = server.action;
    }
    return this.settle(payload, null);
  };

  global.PurrCatAsync = {
    SPEC: SPEC,
    derive: derive,
    Region: Region,
    esc: esc,
    actionLabel: function (id) {
      return ACTION_LABEL[id] || '';
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
