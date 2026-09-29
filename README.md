# PVE 快捷管理工具

基于 Python 标准库，通过 Proxmox VE API 获取 QEMU 虚拟机和 LXC 容器列表，并提供交互式开机、优雅关机操作。菜单支持上下方向键，也支持输入编号后回车。

## 配置

复制模板为脚本同目录的 `config.env`，再填写连接信息：

```bash
cp config.env.example config.env
```

- `PVE_HOST`：PVE 地址，例如 `https://192.168.1.10:8006`
- `PVE_TOKEN_ID`：API Token ID，例如 `root@pam!pve-tools`
- `PVE_TOKEN_SECRET`：创建 Token 时生成的密钥
- `PVE_TLS_VERIFY`：验证 HTTPS 证书，默认开启；仅在使用自签名证书且无法配置信任链时设为 `false`

建议为工具创建仅具备所需虚拟机查询、启动和关机权限的 API Token。`config.env` 已加入忽略列表，不会被 Git 跟踪。

## 运行

```bash
python3 pve_manager.py
```

列表中选择虚拟机后进入操作菜单。关机操作会再次确认；PVE 接受请求后工具会显示返回的任务编号。