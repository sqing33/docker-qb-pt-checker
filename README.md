
# <img width="50" height="50" alt="image" src="https://github.com/user-attachments/assets/8edcccf8-a4ca-4fcb-8224-8d25f15642eb" /> qb-pt-checker 种子站点查询


## 一、项目概述

`qb-pt-checker` 是一个用于查询 qBittorrent 中 PT 种子在已加入的站点是否存在的工具。在使用mp插件`下载器助手`给种子打上站点标签后。聚合种子信息，包括在已加入的站点是否存在、种子名称、保存路径、大小、进度、状态等，并且支持根据路径和状态进行筛选，同时提取了种子的站点详情页注释，可以一键跳转各站点对应的种子详情页。

## 二、 Docker 部署

|    参数     |             说明             |
| :---------: | :--------------------------: |
|   QB_HOST   | qBittorrent 主机地址，带端口 |
| QB_USERNAME |      qBittorrent 用户名      |
| QB_PASSWORD |       qBittorrent 密码       |

```bash
docker run -d \
  --name qb-pt-checker \
  -p 5272:5000 \
  -e QB_HOST=192.168.1.100:8080 \
  -e QB_USERNAME= \
  -e QB_PASSWORD= \
  -v $(pwd):/data \
  --restart always \
  ghcr.io/sqing33/qb-pt-checker
```

```yaml
services:
  qb-pt-checker:
    image: sqing33/qb-pt-checker	# ghcr.io/sqing33/qb-pt-checker
    container_name: qb-pt-checker
    ports:
      - "5272:5000"  # 映射容器的 5000 端口到主机的 5272 端口
    environment:
      - QB_HOST=192.168.1.100:8080  # qBittorrent 主机地址
      - QB_USERNAME=            # qBittorrent 用户名
      - QB_PASSWORD=         # qBittorrent 密码
    volumes:
      - .:/data  # 当前目录挂载到容器内的 /data 目录，配置文件将保存在这里
    restart: always  # 容器自动重启
```

## 三、配置文件

### 1. 配置文件位置和格式

配置文件为 `config.json`，位于 `/data` 目录下，启动时不存在则自动创建。文件格式如下：

```json
{
    "qbittorrent": {
        "host": "192.168.1.100:8080",
        "password": "",
        "username": ""
    },
    "site_link_rules": {
        "一站": {
            "base_url": "https://a.com/detail/"
        }
    },
    "site_alias_mapping": {
        "a": "一站",
        "b": "二站"
    },
    "ui_settings": {
        "active_path_filters": []
    }
}
```

### 2. 配置项说明

- `qbittorrent`：qBittorrent 客户端的连接信息，包括主机地址、用户名和密码。
- `site_link_rules`：当种子注释只有种子 ID 没有完整的链接时，用于生成完整链接的规则。
- `site_alias_mapping`：用于合并有多个 Tracker 的站点打标签出现的多个名称。
- `ui_settings`：前端界面上的筛选设置，由程序自动管理，无需手动修改。

### 3. 配置文件初始化

在应用启动时，会自动检查并创建缺失的配置文件和说明文件。如果配置文件不存在，会尝试从环境变量 `QB_HOST`、`QB_USERNAME` 和 `QB_PASSWORD` 中获取 qBittorrent 的连接信息来创建配置文件。

