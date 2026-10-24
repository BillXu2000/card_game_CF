# 局域网卡牌游戏

浏览器即客户端的多人卡牌游戏服务器，支持 AI 玩家、多房间并行、JSON 导入导出与回退。

## 运行

需要 Python 3.11 或更新版本。

```bash
python -m pip install -r requirements.txt
python -m cardgame                              # 监听 $ZEROTIER_IP（未设置则 127.0.0.1）:8000
python -m cardgame --listen 0.0.0.0 --port 9000
```

或者用 [uv](https://docs.astral.sh/uv/)（自动安装依赖）：

```bash
uv run python -m cardgame
```

然后用浏览器打开 `http://<地址>:<端口>/`，输入用户名登录（首次登录即注册，密码可留空）。

数据（用户、房间、历史）保存在 `data/`，服务器重启后房间会恢复。

## 测试

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

或者 `uv run pytest`。

## 文档

- [需求说明](docs/requirements.md)
- [架构](docs/architecture.md)
