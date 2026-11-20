# Stacks

轻量中文 Docker Compose 编排管理工具，默认统一管理 `/opt/stacks`。

## 功能

- 发现已有 Compose 项目
- 逐行粘贴安装新的 `compose.yaml`，输入 `.完成` 结束
- 扫描其他目录，复制或移动包含 Compose 文件的项目到统一目录
- 更新单个项目：拉取镜像后 `up -d --no-build`
- 查看状态和日志、重启项目
- 启动前执行 `docker compose config --format json` 校验
- 对 privileged、主机网络、主机命名空间、危险 capability、敏感挂载和 build 给出提示
- 不执行 `down -v`、volume prune、源码更新或强制 Git 操作

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
stack organize /srv/old-stacks       # 扫描后确认，默认复制到 /opt/stacks
stack organize /srv/old-stacks --move # 确认后移动原项目
```

安装新编排：

```bash
stack
# 选择 n，输入项目名，逐行粘贴 Compose，单独输入 .完成 结束
```

工具只接受安全项目名，并拒绝覆盖已有目录。安装前会校验配置并展示风险；必须明确输入 `y` 才会启动。整理功能默认只复制，不覆盖已有目标；使用 `--move` 才会移动原目录。扫描默认最多进入 3 层，可用 `--max-depth` 调整。

## 限制

这是 Docker Compose 管理器，不是安全沙箱。Compose 中的挂载、网络、构建和容器权限仍需人工审查。工具不会删除卷或项目数据，但应用升级本身仍可能迁移或改写数据库，重要服务应先做独立数据备份。
