// 工作模式（work / science）：一套面向任务的全局布局开关
//
// 定位提醒：**PurrCat 的核心是通用 Agent（工作模式：对话 + 会话 + 工具），
// 科研工作台（论文/数据/笔记/连接器…）是附加能力**。所以 work 模式必须把科研
// 面板整体收起——不是隐藏两个 tab，而是连中栏外壳一起让出，避免附加功能吃掉主界面。
//
//   science —— 科研工作台：自动打开论文 / 数据 / 笔记三个标签页，
//              侧栏（会话/项目）可见。科研能力一次点击可达。
//   work    —— 对话为主：聊天占满中栏，面板容器与系统插件收起。
//
// 模式只改「哪些东西可见」，不新建面板、不改插件本身；切换 =
// 设置几个插件的 hidden 状态 + 打开指定标签页，全部走既有机制。
import { HOST, groupState, railState, slotMap } from './state.js';
import { collapsePanel, mountPanels, openPanelTab, setContainerHidden, setPanelsSuppressed } from './panel.js';
import { toast } from './queue-status.js';

export type WorkMode = 'work' | 'science';

let mode: WorkMode = 'work';
const listeners: Array<(m: WorkMode) => void> = [];

// panel 区域的显隐在 rail.ts（applySlotHidden）；mode.ts 不能反向 import 它，
// 由宿主启动时注入，保持依赖单向。
let applyPanelArea: ((hidden: boolean) => void) | null = null;

export function registerPanelAreaToggle(fn: (hidden: boolean) => void): void {
  applyPanelArea = fn;
}

// science 模式默认打开的科研三件套（与 SPEC-026..030 的能力一一对应）
const SCIENCE_TABS = ['builtin-paper', 'builtin-data', 'builtin-notebook'];
// science 下保持在容器里的低频科研辅助（不自动打开，点开才见）
const SCIENCE_EXTRA = ['builtin-connectors', 'builtin-environments', 'builtin-contributions'];
// 系统级面板（两种模式都不在白条上直接展示，从设置/更多菜单进）
const SYSTEM_PANELS = ['builtin-evolve'];

export function getMode(): WorkMode {
  return mode;
}

export function onModeChange(fn: (m: WorkMode) => void): void {
  listeners.push(fn);
}

function emit(): void {
  listeners.forEach((fn) => { try { fn(mode); } catch (_) {} });
}

/** science 模式：打开科研三件套，其余标签保留但不强制。 */
function enterScience(): void {
  setPanelsSuppressed(false);
  SCIENCE_TABS.forEach((id) => {
    if (groupState.plugins.some((p) => p.id === id)) openPanelTab(id);
  });
  setContainerHidden(false);
  applyPanelArea?.(false);
  // 外壳在 work 模式下被整体移除过，切回来必须重建（标签列表保留在持久化里）
  if (!HOST.document.querySelector('.wm-ppanel[data-pslot="panel"]')) mountPanels();
  // 低频科研辅助与系统面板收进容器标签里但不激活；不额外隐藏白条区域
}

/** work 模式：聊天为主，科研面板整体让位（外壳与标签列表一起收起）。 */
function enterWork(): void {
  setContainerHidden(true);
  applyPanelArea?.(true);
  setPanelsSuppressed(true);
  collapsePanel();
}

/** 只改内存里的 hidden 状态，不碰 DOM：供 mountAll 之前调用，避免先建后拆。 */
export function applyModeHiddenState(): void {
  if (!railState.hidden) railState.hidden = {};
  (slotMap['panel'] || []).forEach((p) => {
    if (mode === 'work') railState.hidden[p.id] = true;
  });
  if (mode === 'work') (slotMap['panel-container'] || []).forEach((p) => { railState.hidden[p.id] = true; });
}

export function setMode(next: WorkMode, opts?: { persist?: boolean }): void {
  if (next === mode) return;
  mode = next;
  if (next === 'science') enterScience(); else enterWork();
  // 只持久化模式本身；容器可见性由 openPanelTab/setContainerHidden 各自保存
  if (!opts || opts.persist !== false) {
    try {
      HOST.fetch('/api/webmin/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: { value: mode } }),
      }).catch(() => {});
    } catch (_) {}
  }
  // 能力域在会话创建时固化，切模式不会改写已开会话的工具集；
  // 这条提示让用户知道"要生效需要新会话"，而不是以为工具丢了。
  if (groupState.activeSessionId) {
    toast('已切到' + modeLabel(mode) + '：能力变更对新会话生效，当前会话保持原有工具集');
  }
  emit();
}

/** 启动时恢复上次模式（从 manifest.mode 读，manifest.ts 装配）。 */
export function restoreMode(saved: unknown): void {
  if (saved === 'science' || saved === 'work') {
    mode = saved;
    // 恢复时不重复持久化，也不在此处触发布局——mountAll 完成后由 init 应用
  }
}

/** 启动布局应用：mountAll 之后调用一次。 */
export function applyModeLayout(): void {
  if (mode === 'science') enterScience(); else enterWork();
}

export function modeLabel(m: WorkMode): string {
  return m === 'science' ? '科研模式' : '工作模式';
}

export { SCIENCE_TABS, SCIENCE_EXTRA, SYSTEM_PANELS };
