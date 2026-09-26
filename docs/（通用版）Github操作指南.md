# GitHub 通用使用教程

**适用**：任何 Python / 前端 / 后端 / 脚本项目
**平台**：Windows + PowerShell
**难度**：从零到能发布软件

---

## 目录

1. 核心概念
2. 首次配置
3. 创建本地仓库
4. 创建远程仓库
5. 首次上传
6. 日常开发流程
7. `.gitignore` 详解
8. README 写法
9. LICENSE 选择
10. Release（发布软件）
11. 分支与协作
12. 常见问题
13. 快速参考卡

---

## 1. 核心概念

| 名词 | 是什么 | 类比 |
|---|---|---|
| **Git** | 本地版本控制工具 | 电脑里的存档系统 |
| **GitHub** | 云端代码托管网站 | 网盘 |
| **仓库 repo** | 一个项目 | 一个文件夹 |
| **commit** | 一次存档 | 游戏存档点 |
| **push** | 上传到云端 | 备份到网盘 |
| **pull** | 从云端下载 | 从网盘恢复 |
| **branch** | 分支 | 平行世界的存档 |
| **remote origin** | 远程仓库地址 | 网盘地址 |
| **Public / Private** | 公开 / 私有 | 网盘公开 / 加密 |
| **Release** | 发布打包好的软件 | 网盘下载链接 |
| **LICENSE** | 授权协议 | 使用条款 |

**一句话**：**Git 管本机存档，GitHub 把存档放网上。**

---

## 2. 首次配置（只做一次）

### 2.1 装 Git

下载：https://git-scm.com/download/win

安装关键页选 **"Git from the command line and also from 3rd-party software"**（默认就是它）。

### 2.2 加到 PATH（如果 `git --version` 报错）

**用户变量** `Path` 里加：

```
C:\Program Files\Git\bin
```

重启 PowerShell。

### 2.3 设置身份

```powershell
git config --global user.name "你的名字"
git config --global user.email "你的邮箱"
```

**邮箱建议用 GitHub 绑定的邮箱**（GitHub → Settings → Emails 里查）。

### 2.4 验证

```powershell
git --version
git config --global user.name
git config --global user.email
```

### 2.5 生成 Personal Access Token（push 用）

GitHub 从 2021 起不支持密码 push，需要用 Token。

1. GitHub → 头像 → **Settings**
2. 左下 → **Developer settings**
3. **Personal access tokens** → **Tokens (classic)**
4. **Generate new token (classic)**
5. Note 随便填（如 `my-push`）
6. Expiration 选 **90 days**
7. Scopes 勾 **`repo`**
8. **生成，复制**（只显示一次）
9. **妥善保存**（密码管理器 / 记事本）

**push 弹窗要求密码时，粘贴这个 token**。

---

## 3. 创建本地仓库

### 3.1 初始化

在项目目录下：

```powershell
cd C:\path\to\your\project
git init
```

### 3.2 写 `.gitignore`

**根目录新建 `.gitignore`（无扩展名）**。

**Windows 下新建无扩展名文件**：
```powershell
New-Item -Path .gitignore -ItemType File
notepad .gitignore
```

**通用内容**：

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.venv/
venv/
env/

# Node.js（前端）
node_modules/
dist/
build/
.next/

# 编辑器
.vscode/
.idea/
*.swp

# 构建产物
dist_nuitka/
dist_pyinstaller/
*.spec
*.exe
*.zip

# 配置（含本地路径 / 密钥）
config.json
.env
.env.local
*.key
*.pem

# 数据 / 缓存
data/
cache/
*.db
*.sqlite

# 系统
Thumbs.db
Desktop.ini
.DS_Store
```

**按项目类型删减，但 `__pycache__` / `node_modules` / 配置 / 密钥 一定要有。**

### 3.3 加模板配置（可选）

如果项目依赖 `config.json`，加一个 `config.json.example`：

```json
{
  "library_path": "",
  "theme": "light"
}
```

别人克隆后，复制成 `config.json` 填自己的。

### 3.4 首次提交

```powershell
git add .
git commit -m "初始提交"
```

---

## 4. 创建远程仓库

### 4.1 GitHub 网页建仓

1. 打开 https://github.com/new
2. **Repository name**：填项目名
3. **Description**：简介
4. **Public / Private**：自己选（见第 8 节）
5. **不要勾**任何初始化项（README / .gitignore / license）
6. **Create repository**

### 4.2 关联远程

**把 `用户名` 和 `仓库名` 换成你的**：

```powershell
git branch -M main
git remote add origin https://github.com/用户名/仓库名.git
git push -u origin main
```

**第一次 push 会弹窗**，账号 + Token。

---

## 5. 日常开发流程

**改完代码后，三连**：

```powershell
git add .
git commit -m "描述这次改了什么"
git push
```

**就这么简单。**

### commit message 规范

**格式**：`动词：描述`

**常用动词**：
- `新增：` 加功能
- `修复：` 改 bug
- `优化：` 提升性能/体验
- `重构：` 改结构不改功能
- `清理：` 删废弃代码
- `文档：` 只改文档

**例子**：
```
新增：拖拽上传
修复：首屏白屏
优化：查询速度提升 3 倍
重构：拆分 main.py
```

---

## 6. 常用命令

| 命令 | 作用 |
|---|---|
| `git status` | 看当前改动 |
| `git add .` | 全部加入待提交 |
| `git add 文件名` | 单文件加入 |
| `git commit -m "..."` | 提交 |
| `git push` | 上传 |
| `git pull` | 下载远程更新 |
| `git log --oneline` | 看历史 |
| `git diff` | 看未提交的改动 |
| `git clone URL` | 克隆别人的仓库 |
| `git reset HEAD~1` | 撤销最近一次 commit（保留改动） |
| `git checkout -- 文件名` | 撤销某文件改动 |

---

## 7. `.gitignore` 详解

**它决定哪些文件不上传**。

**规则**：
- 一行一个模式
- `/` 结尾表示目录
- `*` 通配
- `!` 取反（例外）

**例子**：
```
*.log          # 所有 .log 文件
!keep.log      # 除了 keep.log
temp/          # temp 目录
**/build/      # 任意层级的 build 目录
```

**误传了怎么办**：

```powershell
git rm --cached 文件名
git commit -m "移除 xxx"
git push
```

---

## 8. README 与 LICENSE

### 8.1 README.md

**每个仓库都该有**。内容建议：

```markdown
# 项目名

一句话简介。

## 功能

- 功能 1
- 功能 2

## 截图

![截图](图片链接)

## 安装 / 运行

```
pip install xxx
python main.py
```

## 技术栈

- Python 3.10
- xxx

## 协议

MIT
```

### 8.2 LICENSE

**不加 LICENSE = 默认保留所有权利**，别人不应使用。

**常用**：

| LICENSE | 特点 |
|---|---|
| **MIT** | 随便用、改、商用，保留版权声明 |
| **GPL v3** | 用、改，但改完也必须开源 |
| **Apache 2.0** | 类似 MIT，附加专利保护 |

**个人项目推荐 MIT**。

**加 LICENSE**：
- 仓库页 → Add file → Create new file → 文件名 `LICENSE`
- 右侧 **Choose a license template** → 选一个

---

## 9. Public vs Private

| | Public | Private |
|---|---|---|
| 别人能看源码 | ✅ | ❌ |
| 别人能下载 Release | ✅ | ❌（除协作者） |
| 免费 | ✅ | ✅ |
| 搜索引擎能索引 | ✅ | ❌ |

**选法**：
- **开源 / 想分享** → Public
- **私用 / 不想公开** → Private

**从 Private 改 Public**：
Settings → 最下方 **Danger Zone** → **Change repository visibility**

---

## 10. Release（发布软件）

**让别人能直接下载打包好的软件**。

### 前提

**仓库必须是 Public**。

### 步骤

**1. 本地打包**

用 PyInstaller / Nuitka / 其他工具，得到可执行文件 + 依赖。

**2. 压成 zip**

例如 `myapp-v1.0.0-win64.zip`。

**3. GitHub 建 Release**

1. 仓库页 → 右侧 **Releases** → **Create a new release**
2. **Choose a tag** → 输入 `v1.0.0` → **Create new tag**
3. **Release title**：`v1.0.0`
4. **Describe this release**：写更新说明
5. **Attach binaries**：拖入 zip
6. **Publish release**

### 结果

仓库右侧出现：

```
Releases
  v1.0.0  Latest
    myapp-v1.0.0-win64.zip
    Source code (zip)
    Source code (tar.gz)
```

**别人点进去就能下载**。

---

## 11. 分支与协作

### 单人开发

**只用 `main` 分支**，不用管。

### 想加新功能又怕搞坏

**开分支**：

```powershell
git checkout -b feature/新功能
# 改代码
git add .
git commit -m "新增：xxx"
git push -u origin feature/新功能
```

**GitHub 上**：会提示 **Compare & pull request** → 点它 → 提交 PR → 自己合并。

**合完删本地分支**：

```powershell
git checkout main
git pull
git branch -d feature/新功能
```

### 和别人协作

1. 对方 Fork 你的仓库
2. 对方改完提 PR
3. 你审核 → 合并或拒绝

### 拉取别人更新

```powershell
git pull
```

---

## 12. 常见问题

**Q1：`git commit` 报 "Author identity unknown"**

没设身份。执行：
```powershell
git config --global user.name "名字"
git config --global user.email "邮箱"
```

**Q2：`git push` 要求密码**

输 **Personal Access Token**，不是登录密码。

**Q3：`git push` 报 "rejected"**

远程有本地没有的提交。先 `git pull` 再 `git push`。

**Q4：误传敏感文件**

```powershell
git rm --cached 文件名
# 编辑 .gitignore 加一行
git commit -m "移除 xxx"
git push
```

**Q5：想撤销上次 commit**

保留改动：
```powershell
git reset HEAD~1
```

不保留改动：
```powershell
git reset --hard HEAD~1
```

**Q6：`.gitignore` 不生效**

已经被 git 跟踪的文件，`.gitignore` 管不住。要先 `git rm --cached`。

**Q7：Token 丢了**

重新生成一个。旧的可删。

**Q8：想克隆别人的仓库**

```powershell
git clone https://github.com/别人/仓库.git
```

**Q9：本地和远程的差距**

```powershell
git status
```
`Your branch is up to date` → 同步。

**Q10：只看某个文件的提交历史**

```powershell
git log --oneline 文件名
```

---

## 13. 快速参考卡

```
┌────────────────────────────────────────────┐
│ 首次配置（只做一次）                        │
│   git config --global user.name "名字"     │
│   git config --global user.email "邮箱"    │
│   生成 Personal Access Token               │
├────────────────────────────────────────────┤
│ 建仓库                                      │
│   git init                                  │
│   写 .gitignore                             │
│   git add .                                 │
│   git commit -m "初始提交"                 │
│   git remote add origin URL                 │
│   git push -u origin main                   │
├────────────────────────────────────────────┤
│ 日常三连                                    │
│   git add .                                 │
│   git commit -m "描述"                     │
│   git push                                  │
├────────────────────────────────────────────┤
│ 查看                                        │
│   git status           ← 当前改动          │
│   git log --oneline    ← 历史              │
│   git diff             ← 未提交改动        │
├────────────────────────────────────────────┤
│ 出问题                                      │
│   git pull             ← 先拉再推          │
│   git reset HEAD~1     ← 撤销上次 commit   │
│   git checkout -- 文件 ← 撤销单文件改动    │
├────────────────────────────────────────────┤
│ 发布软件                                    │
│   1. 打包成 exe                             │
│   2. 压成 zip                               │
│   3. GitHub → Releases → 建 Release → 拖入 │
│   4. 仓库必须 Public                        │
└────────────────────────────────────────────┘
```
