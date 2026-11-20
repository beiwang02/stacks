#!/usr/bin/env bash
set -Eeuo pipefail
install_dir=/usr/local/lib/stacks
mkdir -p "$install_dir"
curl -fsSL https://raw.githubusercontent.com/beiwang02/stacks/main/stack.py -o "$install_dir/stack.py"
chmod 755 "$install_dir/stack.py"
ln -sf "$install_dir/stack.py" /usr/local/bin/stack
printf '安装完成：输入 stack 开始使用。\n'
