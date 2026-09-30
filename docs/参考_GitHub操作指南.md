# GitHub 使用指南（个人项目版）

**项目**：photomanager
**仓库**：https://github.com/QM20071/photomanager

---

## 一、概念速览

| 名词 | 是什么 | 类比 |
|---|---|---|
| **Git** | 本地版本控制工具 | 你电脑里的"存档系统" |
| **GitHub** | 云端代码托管网站 | 网盘 |
| **仓库（repo）** | 一个项目 | 一个文件夹 |
| **commit** | 一次存档 | 游戏存档点 |
| **push** | 上传到云端 | 存档备份到网盘 |
| **pull** | 从云端下载 | 从网盘恢复 |
| **remote origin** | 远程仓库地址 | 网盘地址 |

**一句话**：**Git 在本机管存档，GitHub 帮你把存档放网上。**

---

## 二、首次配置（只做一次）

### 1. 装 Git

下载：https://git-scm.com/download/win

安装时**默认下一步**，关键页选 **"Git from the command line and also from 3rd-party software"**。

### 2. 加到 PATH（如果 `git --version` 报错）

**用户变量** `Path` 里加：

```
C:\Program Files\Git\bin
```

重启 PowerShell。

### 3. 设置身份

```powershell
git config --global user.name "QM20071"
git config --global user.email "2434509500@qq.com"
```

**邮箱建议用 GitHub 绑定的邮箱**，这样提交会显示你的头像。

### 4. 验证

```powershell
git --version
git config --global user.name
git config --global user.email
```

---

## 三、当前项目状态

**已完成**：
- 本地 `git init`
- 写了 `.gitignore` / `config.json.example` / `README.md`
- 首次 `commit`
- 关联远程 `origin`
- 首次 `push`

**远程仓库**：https://github.com/QM20071/photomanager

---

## 四、日常操作（最常用）

**每次改完代码**：

```powershell
cd C:\Users\34100\Desktop\photomanager
git add .
git commit -m "描述这次改了什么"
git push
```

**三行走天下。**

---

## 五、commit message 规范（建议）

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
新增：拖拽整理
修复：首屏缩略图不加载
优化：主题切换实时生效
重构：拆分 main.py
```

---

## 六、常用命令

| 命令 | 作用 |
|---|---|
| `git status` | 看当前有哪些改动 |
| `git add .` | 把所有改动加入"待提交" |
| `git add 文件名` | 只提交某个文件 |
| `git commit -m "..."` | 提交 |
| `git push` | 上传 |
| `git pull` | 下载远程更新 |
| `git log --oneline` | 看历史（简洁） |
| `git diff` | 看未提交的改动 |

---

## 七、`.gitignore` 说明

**它决定哪些文件不上传**。

**当前忽略**：
- `__pycache__/`（Python 缓存）
- `pack_env/`（虚拟环境）
- `.vscode/`（编辑器配置）
- `dist_nuitka/`（打包产物）
- `config.json`（**含你的本地路径，不能传**）
- `data/` `cache/`（图库数据）

**想加新忽略**：编辑 `.gitignore`，加一行。

**如果已误传了**：
```powershell
git rm --cached 文件名
git commit -m "移除 xxx"
git push
```

---

## 八、如果 `push` 弹窗要求密码

**不能输登录密码**，要输 **Personal Access Token**。

**生成**：
1. GitHub → 头像 → **Settings**
2. 左下 → **Developer settings**
3. **Personal access tokens** → **Tokens (classic)**
4. **Generate new token (classic)**
5. Note 随便填
6. Expiration 选 **90 days**
7. Scopes 勾 **`repo`**
8. 生成，**复制**（只显示一次）

**密码框粘贴 token**。

---

## 九、常见问题

**Q：`git commit` 报 "Author identity unknown"？**
A：没设置身份。做"首次配置 第 3 步"。

**Q：`git push` 报 "rejected"？**
A：本地和远程不同步。先 `git pull` 再 `git push`。

**Q：误传了敏感文件？**
A：
```powershell
git rm --cached 文件名
git commit -m "移除 xxx"
git push
```

**Q：想撤销上次提交？**
A：保留改动，撤销 commit：
```powershell
git reset HEAD~1
```

**Q：想看远程仓库和本地是否同步？**
A：`git status`。显示 `Your branch is up to date` → 同步。

---

## 十、下一步建议

1. **加 LICENSE**：GitHub 仓库页 → Add file → Create new file → 文件名 `LICENSE` → 右侧 "Choose a license template" → 选 MIT
2. **加截图到 README**：拖一张图到仓库里，得到 URL，在 README 里用 `![截图](URL)` 引用
3. **多设备开发**：另一台电脑上 `git clone https://github.com/QM20071/photomanager.git`，以后 `git pull` / `git push`

---

## 十一、快速参考卡

```
┌────────────────────────────────────────┐
│ 日常三连                                │
│   git add .                             │
│   git commit -m "描述"                  │
│   git push                              │
├────────────────────────────────────────┤
│ 查看                                    │
│   git status      ← 当前改动            │
│   git log --oneline ← 历史              │
├────────────────────────────────────────┤
│ 出问题                                  │
│   git pull        ← 先拉                │
│   git reset HEAD~1 ← 撤销上次 commit    │
└────────────────────────────────────────┘
```