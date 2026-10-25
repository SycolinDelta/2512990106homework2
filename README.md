# 代码审查 Workflow（Homework2）

**Simple Workflow MVP：多个 Agent 协作，自动完成「审查 → 修复 → 验证」的代码修复流水线。**

用户提交一段代码（或代码文件路径），Workflow 会依次经过 4 个 Agent 协作：
**接收代码 → 审查问题 → 自动修复 → 验证修复是否生效**，最终在终端输出**修复后的完整结果**。

> 与 Homework1 的关系：交互方式完全一致（路径/代码输入、`END` 结束、`exit` 退出），
> 区别在于 Homework1 输出「修改建议 + 注释」，Homework2 输出「自行修复后的结果」。
> Homework1 的审查经验（严格基于源码、宁可少报不可错报）被复用到本项目的 reviewer Agent 中。

## 项目简介

| 项 | 说明 |
|---|---|
| Workflow 方向 | 代码审查流程：编码 → 审查 → 修复 → 验证（PPT 中的「代码审查流程」） |
| Agent 数量 | 4 个：coder / reviewer / fixer / tester |
| 流程控制 | 顺序执行 + 条件分支 + 受控循环（审查-修复最多 3 轮） |
| Agent 通信 | 消息投递（Message）+ 共享状态（WorkflowState 黑板） |
| 客观依据 | 内置 C++ 确定性静态检查器，不依赖大模型即可判断修复是否生效 |
| 源文件安全 | **全程只读**，修复结果只输出到终端，不会修改 `test.cpp` 等源文件 |

## 技术栈

- Python 3.11
- LangChain（`langchain-openai` 的 `ChatOpenAI` 调用大模型，与 Homework1 相同的接法）
- 自研轻量编排器（`workflow/`，不依赖 LangGraph 的状态图）
- 大模型：智谱 AI glm-4-flash

## 环境配置

1. 创建并激活 conda 虚拟环境（Python 3.11）：

```bash
conda create -n homework2 python=3.11
conda activate homework2
```

2. 安装依赖：

```bash
pip install -r requirements.txt
```

> 依赖只有两个：`langchain-openai` 与 `python-dotenv`。
> 静态检查器是纯标准库实现。

3. 配置 API Key：

将 `.env.example` 重命名（去掉 `.example` 后缀）为 `.env`，然后填入你自己的智谱 API Key：

```env
LLM_API_KEY=你的智谱API Key
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
LLM_MODEL=glm-4-flash
```

> 智谱开放平台：https://open.bigmodel.cn ，注册实名后创建 API Key 即可。
> 注意：`.env` 包含个人密钥，不要上传到代码仓库或公开分享。

## 运行方式

### 交互模式（与 Homework1 相同）

```bash
python main.py
```

使用示例：

- 输入本地代码文件路径（如 `test.cpp`），Workflow 会读取文件后开始审查-修复-验证；
  一次只处理一个文件，多个文件请逐个提交；
- 也可以直接输入一段代码（支持用回车换行）；
- 输入完成后单独输入一行 `END` 并回车以结束录入；
- 输入 `exit` 退出程序。

仓库中的 `test.cpp`（哈夫曼树中序遍历）是**故意写错**的样例，可直接作为演示输入。
Workflow 会自动发现并修复其中的问题，但**不会改动这个文件本身**。

### 其它命令行参数

```bash
python main.py --file test.cpp      # 一次性处理一个文件（不进交互循环）
python main.py --graph              # 打印 Workflow 流程图（文字版 + mermaid）
python main.py --log run.json       # 把执行日志（事件轨迹 + 全部 Agent 消息）写成 JSON
python main.py --max-rounds 5       # 修改审查-修复循环上限（默认 3）
python main.py --verbose            # 实时打印每个节点的执行进度
```

## 输出说明

每次运行输出固定三部分：

1. **一、修复概览** —— 原始问题数、审查结论、逐条修复清单（原第几行、改前 / 改后、原因）；
2. **二、修复后的完整代码** —— 可直接复制使用；终端中标注了源文件未被修改；
3. **三、验证结论** —— 静态检查修复前后的问题数、已修复 / 仍未修复 / 本次新引入。

最后附「执行过程」（节点顺序与每轮审修记录）和「修复前后差异」（unified diff）。

## 对 `test.cpp` 的处理结果（演示预期）

`test.cpp` 中有两个故意写错的地方（本题输入样例，按要求保持原样不改）：

| 位置 | 问题 | 修复 |
|---|---|---|
| 第 50 行 | `priority_queue<HuffNode, vector<HuffNode*>, cmp>` 第一个模板参数是元素类型，与容器/比较器的 `HuffNode*` 不一致，无法编译 | 改为 `priority_queue<HuffNode*, vector<HuffNode*>, cmp>` |
| `delTree` 函数 | `if (root != nullptr) return;` 判空写反；且先 `delete` 后再访问 `root->left` | 判空改为 `== nullptr`，并按「先递归释放左右子树、最后释放自身」重写 |

运行后这两个问题会被修复并验证通过，`test.cpp` 文件本身一个字节都不会变。

## 目录结构

```
homework2/
├─ main.py                    # 主程序入口（交互方式与 Homework1 一致）
├─ output.py                  # 结果渲染（修复概览 / 修复后代码 / 验证结论）
├─ test.cpp                   # 测试样例（故意写错，全程只读，不会被修改）
├─ requirements.txt           # Python 依赖
├─ .env.example               # 配置模板（重命名为 .env 后填入 API Key）
├─ README.md                  # 本文件：使用说明
├─ Design.md                  # 设计文档：架构、流程、状态与消息协议
├─ workflow/                  # 自研 Workflow 编排层
│  ├─ state.py                #   共享状态（黑板）
│  ├─ message.py              #   Agent 间消息协议
│  ├─ graph.py                #   声明式流程定义（节点 / 边 / 条件 / 循环上限）
│  └─ orchestrator.py         #   执行引擎（顺序、分支、循环、重试、日志）
├─ agents/                    # 四个 Agent 节点
│  ├─ base.py                 #   Agent 基类 + 大模型客户端
│  ├─ coder.py                #   节点1：接收原始代码
│  ├─ reviewer.py             #   节点2：审查（复用 Homework1 审查经验）
│  ├─ fixer.py                #   节点3：自动修复
│  └─ tester.py               #   节点4：验证修复结果
└─ tools/                     # 确定性工具
   ├─ file_reader.py          #   只读文件读取（UTF-8/GBK/latin-1 兼容）
   └─ cpp_static_checker.py   #   C++ 静态检查 + 规则自动修复
```

## 常见问题

- **提示「大模型不可用」**：检查 `.env` 是否填了 `LLM_API_KEY`、是否执行了 `pip install -r requirements.txt`
  （报错信息里会给出具体的失败原因）。
- **换一个代码文件**：`python main.py --file 你的文件.cpp`，或交互模式下直接输入文件路径。
- **静态检查器目前针对 C++**：其它语言会跳过静态检查，只由大模型审查与修复，
  验证环节会如实报告「无可用的确定性检查」。
