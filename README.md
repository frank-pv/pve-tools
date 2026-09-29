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

## PVE 权限

此工具只需要以下两项虚拟机权限，不需要 `Sys.Audit` 或管理员权限：

- `VM.Audit`：查看虚拟机列表和信息。
- `VM.PowerMgmt`：启动虚拟机或容器，以及执行优雅关机。

### 通过 Web 界面设置

1. 打开 **Datacenter → Permissions → Roles → Create**。Role ID 填 `VmPowerTool`，权限列表中只勾选 `VM.Audit` 和 `VM.PowerMgmt`，保存角色。
2. 打开 **Datacenter → Permissions → Permissions → Add → User Permission**。Path 填 `/vms`，User 选择 API Token 所属用户（例如 `pve-tool@pve`），Role 选择 `VmPowerTool`，勾选 **Propagate** 后保存。
3. 继续在 **Permissions → Add → API Token Permission** 添加 Token 权限。Path 同样填 `/vms`，API Token 选择对应 Token（例如 `pve-tool@pve!manager`），Role 选择 `VmPowerTool`，勾选 **Propagate** 后保存。

第 3 步适用于创建 Token 时启用了默认的 **Privilege Separation**（建议保持启用）的情况。启用后，Token 的有效权限是所属用户与 Token 自身权限的交集，所以第 2、3 步都要做。若只管理单台虚拟机，可将两处 Path 都改成 `/vms/<VMID>`，例如 `/vms/101`。

可在 PVE Shell 创建并授权同一角色：

```bash
pveum role add VmPowerTool --privs "VM.Audit VM.PowerMgmt"
pveum acl modify /vms --users 'pve-tool@pve' --roles VmPowerTool
pveum acl modify /vms --tokens 'pve-tool@pve!manager' --roles VmPowerTool
```

示例假定 API Token 属于 `pve-tool@pve`，Token 名称为 `manager`。将命令中的用户和 Token ID 换成实际值。若只管理特定虚拟机，可把 ACL 路径 `/vms` 改为 `/vms/<VMID>`。

建议创建 Token 时保留默认的 **Privilege Separation**。启用后，PVE 会取所属用户与 Token 各自权限的交集，因此需要像示例一样分别给用户和 Token 授权；也可在 PVE 的 **Datacenter → Permissions** 中创建角色并配置 ACL。详情见 [PVE 官方权限管理文档](https://pve.proxmox.com/pve-docs/pveum.1.html)。

## 运行

```bash
python3 pve_manager.py
```

列表中选择虚拟机后进入操作菜单。关机操作会再次确认；PVE 接受请求后工具会显示返回的任务编号。