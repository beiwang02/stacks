#!/usr/bin/env python3
"""中文 Docker Compose 项目管理器，默认管理 /opt/stacks。"""
from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(os.environ.get("STACKS_ROOT", "/opt/stacks"))
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")


def fail(msg: str, code: int = 1):
    print(f"错误：{msg}", file=sys.stderr)
    raise SystemExit(code)


def project_path(name: str) -> Path:
    if not NAME_RE.fullmatch(name):
        fail("项目名只允许小写字母、数字、短横线和下划线，且不能以短横线开头。")
    return ROOT / name


def compose_file(path: Path) -> Path:
    for name in COMPOSE_NAMES:
        candidate = path / name
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    fail(f"项目 {path.name} 没有找到 Compose 文件。")


def run(cmd: list[str], cwd: Path | None = None, capture=False) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    for key in ("DOCKER_HOST", "COMPOSE_FILE", "COMPOSE_PROJECT_NAME"):
        env.pop(key, None)
    return subprocess.run(cmd, cwd=cwd, env=env, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.STDOUT if capture else None)


def require_tools():
    for tool in ("docker",):
        if not shutil.which(tool):
            fail(f"找不到 {tool}，请先安装 Docker。")
    if run(["docker", "compose", "version"], capture=True).returncode:
        fail("Docker Compose 不可用，请确认已安装 Compose 插件。")


def projects() -> list[Path]:
    if not ROOT.is_dir():
        return []
    return sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.is_symlink()
                  and any((p / n).is_file() and not (p / n).is_symlink() for n in COMPOSE_NAMES))


def discover(source: Path, max_depth: int = 3) -> list[Path]:
    """Find Compose project directories below source without following symlinks."""
    source = source.expanduser().resolve()
    if not source.is_dir():
        fail(f"扫描目录不存在：{source}")
    found = []
    for base, dirs, files in os.walk(source, followlinks=False):
        base_path = Path(base)
        depth = len(base_path.relative_to(source).parts)
        dirs[:] = [d for d in dirs if not (base_path / d).is_symlink()
                   and d not in {".git", "node_modules", "__pycache__"}]
        if depth > max_depth:
            dirs[:] = []
            continue
        if any(name in files for name in COMPOSE_NAMES):
            found.append(base_path)
            dirs[:] = []
    return sorted(found)


def organize(source: str, move=False, max_depth=3):
    source_path = Path(source).expanduser()
    if max_depth < 0:
        fail("最大扫描深度不能小于 0。")
    candidates = discover(source_path, max_depth)
    if not candidates:
        print("没有发现包含 Compose 文件的项目。")
        return
    plan = []
    for item in candidates:
        name = item.name
        if not NAME_RE.fullmatch(name):
            print(f"跳过 {item}：目录名不符合项目名规则")
            continue
        target = ROOT / name
        if target.exists() or target.is_symlink():
            print(f"跳过 {item}：目标已存在 {target}")
            continue
        plan.append((item, target))
    if not plan:
        print("没有可整理的项目。")
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    print("将整理以下项目：")
    for item, target in plan:
        print(f"  {item} -> {target}")
    if not confirm("确认整理到指定目录？"):
        print("已取消。")
        return
    for item, target in plan:
        if move:
            shutil.move(str(item), str(target))
        else:
            shutil.copytree(item, target, symlinks=True)
    print(f"已整理 {len(plan)} 个项目到 {ROOT}。")


def inspect_config(path: Path) -> tuple[dict, list[str]]:
    f = compose_file(path)
    result = run(["docker", "compose", "-f", str(f), "config", "--format", "json"], cwd=path, capture=True)
    if result.returncode:
        print(result.stdout or "Compose 配置校验失败。")
        fail("Compose 配置校验失败，未执行启动。")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        fail("Docker Compose 返回的配置不是有效 JSON。")
    risks = []
    services = data.get("services", {})
    for service, cfg in services.items():
        if cfg.get("privileged"):
            risks.append(f"服务 {service} 使用 privileged")
        if cfg.get("network_mode") in ("host", "container:host"):
            risks.append(f"服务 {service} 使用主机网络")
        if cfg.get("pid") == "host" or cfg.get("ipc") == "host":
            risks.append(f"服务 {service} 共享主机命名空间")
        for cap in cfg.get("cap_add", []) or []:
            if str(cap).upper() in {"SYS_ADMIN", "NET_ADMIN", "ALL"}:
                risks.append(f"服务 {service} 添加高权限 capability: {cap}")
        for vol in cfg.get("volumes", []) or []:
            source = vol.get("source", "") if isinstance(vol, dict) else str(vol).split(":", 1)[0]
            if source in ("/", "/var/run/docker.sock", "/etc", "/proc", "/sys", "/dev"):
                risks.append(f"服务 {service} 挂载敏感主机路径: {source}")
        if cfg.get("build"):
            risks.append(f"服务 {service} 包含 build，默认不会构建镜像")
    print(f"配置通过：{len(services)} 个服务")
    if risks:
        print("发现需要确认的项目：")
        for risk in risks:
            print(f"  - {risk}")
    return data, risks


def confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes", "是")


def update(name: str, build=False):
    path = project_path(name)
    if not path.is_dir() or path.is_symlink():
        fail("项目不存在或不是安全的项目目录。")
    inspect_config(path)
    f = compose_file(path)
    if build:
        print("将执行源码构建，可能改变运行中的服务。")
    else:
        print("将只拉取镜像并更新，不构建源码、不删除卷。")
    if not confirm("确认继续？"):
        print("已取消。"); return
    pull = run(["docker", "compose", "-f", str(f), "pull"], cwd=path)
    if pull.returncode:
        fail("镜像拉取失败，已停止，不使用旧镜像继续启动。")
    cmd = ["docker", "compose", "-f", str(f), "up", "-d"] + ([] if build else ["--no-build"])
    if run(cmd, cwd=path).returncode:
        fail("项目更新失败，请查看日志。")
    print("更新完成。")


def install_paste(name: str):
    path = project_path(name)
    if path.exists() or path.is_symlink():
        fail("目标项目目录已经存在，为避免覆盖，安装已停止。")
    print("请逐行粘贴 Compose 内容，单独输入 .完成 结束：")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".完成":
            break
        lines.append(line)
    content = "\n".join(lines).strip() + "\n"
    if not content.strip():
        fail("没有读取到 Compose 内容。")
    ROOT.mkdir(parents=True, exist_ok=True)
    path.mkdir()
    (path / "compose.yaml").write_text(content, encoding="utf-8", newline="\n")
    inspect_config(path)
    print(f"将安装到：{path}")
    if not confirm("确认拉取镜像并启动？"):
        print(f"已取消。配置保留在 {path}，未启动。")
        return
    f = compose_file(path)
    if run(["docker", "compose", "-f", str(f), "pull"], cwd=path).returncode:
        fail("镜像拉取失败，未启动。")
    if run(["docker", "compose", "-f", str(f), "up", "-d", "--no-build"], cwd=path).returncode:
        fail("启动失败，请查看日志。")
    print("安装完成。")


def menu():
    require_tools()
    while True:
        print("\nStacks · 编排管理")
        items = projects()
        for i, p in enumerate(items, 1): print(f"  {i}. {p.name}")
        print("  n. 安装新项目（逐行粘贴 Compose）")
        print("  o. 扫描并整理其他目录")
        print("  q. 退出")
        choice = input("选择：").strip()
        if choice == "q": return
        if choice == "n":
            name = input("项目名：").strip()
            install_paste(name); continue
        if choice == "o":
            source = input("扫描目录：").strip()
            organize(source, move=confirm("是否移动原目录？（否：复制）")); continue
        if choice.isdigit() and 1 <= int(choice) <= len(items):
            name = items[int(choice)-1].name
            action = input(f"{name}：u 更新，l 日志，s 状态，r 重启，q 返回：").strip().lower()
            path = project_path(name); f = compose_file(path)
            if action == "u": update(name)
            elif action == "l": run(["docker", "compose", "-f", str(f), "logs", "--tail=100"], cwd=path)
            elif action == "s": run(["docker", "compose", "-f", str(f), "ps"], cwd=path)
            elif action == "r":
                if confirm("确认重启项目？"): run(["docker", "compose", "-f", str(f), "restart"], cwd=path)
        else: print("无效选择。")


def main():
    parser = argparse.ArgumentParser(description="Stacks 中文 Docker Compose 管理器")
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("list", help="列出 Compose 项目")
    u = sub.add_parser("update", help="更新项目")
    u.add_argument("name"); u.add_argument("--build", action="store_true")
    o = sub.add_parser("organize", help="扫描并整理 Compose 项目")
    o.add_argument("source", help="待扫描目录")
    o.add_argument("--move", action="store_true", help="移动原目录；默认复制")
    o.add_argument("--max-depth", type=int, default=3)
    args = parser.parse_args()
    if args.action == "list":
        for p in projects(): print(p.name)
    elif args.action == "update":
        require_tools(); update(args.name, args.build)
    elif args.action == "organize":
        organize(args.source, args.move, args.max_depth)
    else: menu()

if __name__ == "__main__": main()
