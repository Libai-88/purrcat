# PurrCat 文档中心

本目录是 PurrCat 的开发者文档入口，分为三大板块：

## 开发指南（`docs/develop/`）

技术栈、目录地图、运行拓扑、启动与验证命令，以及前端 / 后端 / 桌面壳的改动指南。

- [开发指南总览](develop/README.md)
  - [后端开发](develop/backend.md)
  - [前端开发](develop/frontend.md)
  - [桌面壳与安装器](develop/installer.md)

## API 参考（`docs/api/`）

后端 `src/server` 的全部 HTTP / WebSocket / SSE 接口，按模块拆分，逐接口给出参数、响应与调用示例。

- [API 总览与模块索引](api/README.md)

## 插件开发（`docs/plugins/`）

PurrCat 专属的四类扩展插件的开发指南，含各自专有词汇表与最小可运行示例。

- [插件体系总览](plugins/README.md)
  - [Sensor 开发（感官中枢）](plugins/sensor.md)
  - [Graph 开发（任务编排中枢）](plugins/graph.md)
  - [AgentLoop 开发（主循环范式）](plugins/agentloop.md)
  - [UI Plugin 开发（极简模式界面插件）](plugins/ui-plugin.md)

## 论文库（`docs/papers.md`）

面向科研场景的内核能力：PDF 导入本机论文库，按页读原文、把引文定位到具体页码、
核对断言是否有原文支撑。

- [论文库与证据核对](papers.md)

## 研究笔记（`docs/notebook.md`）

把一次研究写成由块组成的文档：正文、论文原文引文、数据查询收据、可计算的表格，
以及引用前两者的结论。

- [研究笔记](notebook.md)

## 数据工作台（`docs/data.md`）

把本机数据文件变成可回指的数据集：导入、检查结构与质量、查询并留下可引用的收据。

- [数据工作台](data.md)

## 科研自动化（`docs/automation.md`）

到点让 Agent 跑一段指定的指示，并留下每次运行的回执。

- [科研自动化](automation.md)

## 科研连接器（`docs/connectors.md`）

检索 arXiv、OpenAlex、Crossref、PubMed、Zenodo、UniProt，
把结果拉进本机库并留下来源凭据。

- [科研连接器](connectors.md)

## 便携版（`docs/portable.md`）

解压即用，数据跟着目录走，不写注册表、不依赖 Docker。

- [便携版](portable.md)

## 贡献工作区（`docs/contributions.md`）

把本机改动变成草稿 PR：工作区 → diff → 审阅 → 发布。Agent 不发布，发布权留给用户。

- [贡献工作区](contributions.md)

## 科研环境（`docs/environments.md`）

只读探测本机的 Python、Git、uv、Node、Docker 与执行能力。

- [科研环境](environments.md)

## 面板异步状态（`docs/async-state.md`）

论文 / 数据 / 笔记三个面板共用的状态语义：有哪些数据、请求在做什么、
业务结果是什么，以及失败后该重试还是该重新导入。

- [面板异步状态](async-state.md)

---

> API 文档与 `src/server` 真实路由的一致性由 `scripts/check_api_docs.py` 校验（CI 工作流 `.github/workflows/api-docs.yml`）。
