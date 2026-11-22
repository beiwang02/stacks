# Stacks

轻量中文 Docker Compose 编排管理工具，默认统一管理 `/opt/stacks`。当前版本 `0.2.0`。

## 功能

- 发现已有 Compose 项目
- 逐行粘贴安装新的 `compose.yaml`，输入 `.完成` 结束
- 扫描其他目录，复制或移动包含 Compose 文件的项目到统一目录
- 更新单个项目：拉取镜像后 `up -d --no-build`
- 独立执行 `start`、`stop`、`restart`、`status`、`logs`、`config`、`pull`
- 将项目目录备份为 `.tar.gz`，默认不覆盖已有备份
- `self-update` 更新 Stacks 工具自身，并校验下载脚本后原子替换
- 多重确认删除项目：默认保留 Docker 数据卷，并将编排目录归档到 `.removed/`
- `--data` 才允许删除 Compose 数据卷，并要求额外输入 `DELETE DATA`
- 查看状态和日志、重启项目
- 启动前执行 `docker compose config --format json` 校验
- 对 privileged、主机网络、主机命名空间、危险 capability、敏感挂载和 build 给出提示
- 不默认执行 `down -v`、volume prune、源码更新或强制 Git 操作；删除数据卷必须显式使用 `--data` 并完成额外确认

## 安装

服务器上执行：

```bash
sudo mkdir -p /usr/local/lib/stacks
sudo curl -fsSL https://raw.githubusercontent.com/beiwang02/stacks/main/stack.py -o /usr/local/lib/stacks/stack.py
sudo chmod 755 /usr/local/lib/stacks/stack.py
sudo ln -sf /usr/local/lib/stacks/stack.py /usr/local/bin/stack
```

## 使用

```bash
stack                 # 中文菜单
stack list            # 列出项目
stack update sub-store
stack update sub-store --build  # 显式允许构建，仍会先确认
stack start sub-store
stack stop sub-store
stack restart sub-store
stack status sub-store
stack logs sub-store --tail 200
stack config sub-store
stack pull sub-store
stack backup sub-store -o /opt/backups/sub-store.tar.gz
stack self-update                  # 更新 Stacks 自身，确认后原子替换脚本
stack remove sub-store             # 移除容器并归档编排目录，保留数据卷
stack remove sub-store --data      # 危险：额外确认后删除数据卷，再归档目录
stack organize /srv/old-stacks       # 扫描后确认，默认复制到 /opt/stacks
stack organize /srv/old-stacks --move # 确认后移动原项目
```

安装新编排：

```bash
stack
# 选择 n，输入项目名，逐行粘贴 Compose，单独输入 .完成 结束
```

工具只接受安全项目名，并拒绝覆盖已有目录。安装前会校验配置并展示风险；必须明确输入 `y` 才会启动。整理功能默认只复制，不覆盖已有目标；使用 `--move` 才会移动原目录。扫描默认最多进入 3 层，可用 `--max-depth` 调整。删除必须在交互式终端进行，先核对 Compose 项目归属，再输入完整项目名并确认；原目录默认移入同级 `.removed/`，方便找回。`--data` 还要求再次输入项目名和 `DELETE DATA`，防止误删数据卷。

## 限制

这是 Docker Compose 管理器，不是安全沙箱。Compose 中的挂载、网络、构建和容器权限仍需人工审查。删除默认保留卷，但 `remove --data` 会删除 Compose 管理的卷且可能无法恢复；重要服务应先做独立数据备份。自更新只信任 GitHub main 上能通过脚本头、版本号和 Python 编译检查的内容。
