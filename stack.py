#!/usr/bin/env python3
"""中文 Docker Compose 项目管理器，默认管理 /opt/stacks。"""
from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from urllib.request import Request, urlopen

VERSION = "0.2.0"
RAW_URL = "https://raw.githubusercontent.com/beiwang02/stacks/main/stack.py"

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


def require_project(name: str) -> tuple[Path, Path]:
    path = project_path(name)
    if not path.is_dir() or path.is_symlink():
        fail("项目不存在或不是安全的项目目录。")
    return path, compose_file(path)


def remove(name: str, data=False):
    path, f = require_project(name)
    if not sys.stdin.isatty():
        fail("删除必须在交互式终端操作，不接受管道确认。")
    path = path.resolve()
    f = path / f.name
    cmd = ["docker", "compose", "-f", str(f)]
    result = run(cmd + ["config", "--format", "json"], cwd=path, capture=True)
    try:
        compose_name = json.loads(result.stdout)["name"] if not result.returncode else None
    except (ValueError, TypeError, KeyError):
        compose_name = None
    if not isinstance(compose_name, str) or not NAME_RE.fullmatch(compose_name):
        fail("无法确认实际 Compose 项目名，未执行删除。")
    result = run(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={compose_name}",
                  "--format", '{{.Label "com.docker.compose.project.working_dir"}}'], cwd=path, capture=True)
    if result.returncode or any(not line or Path(line).resolve() != path for line in result.stdout.splitlines()):
        fail("无法核对容器归属，或发现同名项目的容器来自其他目录，未执行删除。")
    print(f"目录：{path}\n实际 Compose 项目：{compose_name}")
    print("将停止并移除项目容器，原目录整体移入 .removed，保留目录内文件和绑定挂载数据。")
    print("本次会尝试删除 Compose 管理的卷。" if data else "本次不会删除 Docker 数据卷。")
    if input(f"请输入项目名 {name} 以继续：").strip() != name:
        print("项目名不匹配，已取消。")
        return
    if not confirm("确认移除容器并归档项目目录？"):
        print("已取消。")
        return
    if data:
        print("警告：--data 会删除该 Compose 项目管理的命名卷和匿名卷，数据可能无法恢复。")
        if input(f"再次输入项目名 {name}：").strip() != name:
            print("项目名不匹配，已取消。")
            return
        if input("请输入 DELETE DATA 才能删除数据卷：").strip() != "DELETE DATA":
            print("危险确认不匹配，已取消。")
            return
    archive = path.parent / ".removed"
    if archive.is_symlink():
        fail("归档目录是符号链接，未执行删除。")
    try:
        archive.mkdir(mode=0o700, exist_ok=True)
        slot = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=archive))
    except OSError as exc:
        fail(f"无法创建归档位置，未执行删除：{exc}")
    target = slot / name
    try:
        if run(cmd + ["-p", compose_name, "down"] + (["-v"] if data else []), cwd=path).returncode:
            fail("Compose 移除失败，原目录未移动；容器或卷可能已部分移除。")
        path.rename(target)
    except OSError as exc:
        fail(f"操作未完整完成，请检查容器状态；原目录未归档：{exc}")
    finally:
        if not target.exists():
            slot.rmdir()
    print(f"项目目录已归档：{target}")


def self_update():
    target = Path(__file__).resolve()
    if not target.is_file():
        fail("无法定位当前脚本文件。")
    print(f"将从 GitHub 更新：{RAW_URL}")
    if not confirm("确认更新 Stacks 工具本身？"):
        print("已取消。")
        return
    try:
        request = Request(RAW_URL, headers={"User-Agent": "stacks-self-update"})
        with urlopen(request, timeout=30) as response:
            content = response.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024 or not content.startswith(b"#!") or not re.search(rb'^VERSION = "[0-9]+\.[0-9]+\.[0-9]+"$', content, re.M):
            fail("下载内容不像有效的 Stacks Python 脚本，已停止。")
        compile(content, str(target), "exec")
        if target.read_bytes() == content:
            print(f"已是最新版本：{VERSION}")
            return
        mode = target.stat().st_mode
        fd, temp_name = tempfile.mkstemp(prefix=".stack-update-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as temp:
                temp.write(content)
            os.chmod(temp_name, mode)
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
    except (OSError, SyntaxError) as exc:
        fail(f"更新失败，原脚本未替换：{exc}")
    print(f"更新完成：{target}")


def update(name: str, build=False):
    path, f = require_project(name)
    inspect_config(path)
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
        print("  d. 删除项目（多重确认）")
        print("  q. 退出")
        choice = input("选择：").strip()
        if choice == "q": return
        if choice == "n":
            name = input("项目名：").strip()
            install_paste(name); continue
        if choice == "o":
            source = input("扫描目录：").strip()
            organize(source, move=confirm("是否移动原目录？（否：复制）")); continue
        if choice == "d":
            name = input("项目名：").strip()
            remove(name); continue
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
    parser.add_argument("--version", action="version", version=f"Stacks {VERSION}")
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("list", help="列出 Compose 项目")
    sub.add_parser("self-update", help="更新 Stacks 工具自身")
    u = sub.add_parser("update", help="更新项目")
    u.add_argument("name"); u.add_argument("--build", action="store_true")
    d = sub.add_parser("remove", help="删除项目；默认保留数据卷")
    d.add_argument("name")
    d.add_argument("--data", action="store_true", help="危险：同时删除 Compose 数据卷")
    o = sub.add_parser("organize", help="扫描并整理 Compose 项目")
    o.add_argument("source", help="待扫描目录")
    o.add_argument("--move", action="store_true", help="移动原目录；默认复制")
    o.add_argument("--max-depth", type=int, default=3)
    args = parser.parse_args()
    if args.action == "list":
        for p in projects(): print(p.name)
    elif args.action == "self-update":
        self_update()
    elif args.action == "remove":
        require_tools(); remove(args.name, args.data)
    elif args.action == "update":
        require_tools(); update(args.name, args.build)
    elif args.action == "organize":
        organize(args.source, args.move, args.max_depth)
    else: menu()

if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\n操作已中断，请核对当前状态。", file=sys.stderr)
        raise SystemExit(130)
