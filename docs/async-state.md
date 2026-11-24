# 面板异步状态

论文、数据、笔记三个面板的「现在是什么状态」用同一套说法。

## 为什么不是一张枚举

同样叫「状态」，底下其实是三件正交的事：

| 轴 | 问的问题 | 取值 |
| --- | --- | --- |
| `data` | 屏幕上现在有什么 | `none` `partial` `stale` `complete` |
| `request` | 请求在做什么 | `idle` `first_load` `refresh` `submitting` `cancelling` `cancelled` `completed` |
| `result` | 业务结果是什么 | `pending` `ok` `empty` `failed` `unavailable` |

三轴组合出最终状态。拆成三轴才分得清这几种本来会混在一起的情况：

- **刷新失败**和**首次加载失败**都是 `failed`，但前者要**留住上一次的结果**
  并说明那不是最新结果，后者没有旧内容可留。
- **原文件丢了**是 `unavailable` 而不是 `failed`——重试没有用，得重新导入。
- **加载中**不能显示成「暂无数据」：请求还在飞（`result=pending`），
  不等于没有数据。

## 一份词表

词表与规则表只写在 `ui/web-minimal/assets/async-state.js` 的一段 JSON 里：

- **后端**通过 `src/utils/async_state.py` 从那个文件读；
- **前端**加载同一个文件。

契约测试（`tests/l3/test_async_state_contract.py`）穷举三轴全部组合，
断言 Python 与 JS 推出同一个状态。两边不会各自漂移。

## 职责分工

| 谁 | 知道什么 |
| --- | --- |
| 服务端 | 业务结果（`result`）、失败原因（`reason`）、用户下一步（`action`） |
| 客户端 | 屏幕上有没有内容（`data`）、请求在做什么（`request`） |

服务端**不知道**客户端屏幕上还留着什么，所以 `data` 轴由客户端给。
接口在出错时把 `status` 一并回给客户端：

```json
{
  "detail": "原文件已丢失，无法读取，也不会用旧数据代替",
  "status": {
    "state": "unavailable",
    "data": "none",
    "request": "idle",
    "result": "unavailable",
    "reason": "source_missing",
    "action": "import"
  }
}
```

## 面板怎么用

```js
var region = new PurrCatAsync.Region(elBody);

// 请求开始：首次显示骨架屏；刷新时保留旧内容，只挂一条「更新中」。
region.begin('first_load');

// 请求回来：data 由客户端给，result 由服务端给。
region.settle({ data: 'complete', request: 'idle', result: 'ok' }, render);

// 失败：服务端给了 status 就用它，能分清「不可用」和「失败」。
region.fail(err, retry);
```

`Region` 守住几条约定：

- 刷新失败**保留上一次的内容**，在顶上挂一条提示说明那不是最新结果；
- 换对象时调 `reset()` 清掉旧内容——留着就是「把旧对象的数据冒充成新对象的」；
- 空态按原因给不同的下一步，不复用同一个空壳；
- 骨架屏只画灰色块，不伪造数值。

## 与认识论分层的关系

这套状态**只说界面处于什么状态**，从不说「这个结论是对的」。

科学验证由 `acceptance` / `verification` 那套封闭词表负责
（见 [papers.md](papers.md)）。两者互不冒充：状态字典里没有
`acceptance` / `verification` 字段，有测试盯着这件事。

## 代码位置

| 关注点 | 位置 |
| --- | --- |
| 词表与规则表（前后端共用） | `ui/web-minimal/assets/async-state.js` |
| 面板状态外观 | `ui/web-minimal/assets/async-state.css` |
| Python 侧读词表与推导 | `src/utils/async_state.py` |
| 领域事实 → 状态 | `src/utils/panel_state.py` |
| 接口错误带状态 | `src/server/api/research_status.py` |

设计与验收标准见
[../tests/specs/SPEC-031-panel-async-state.md](../tests/specs/SPEC-031-panel-async-state.md)。
