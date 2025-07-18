# app.py
import collections
import json
import os
import math
from flask import Flask, jsonify, render_template, request
from qbittorrentapi import Client

app = Flask(__name__)
DATA_DIR = '.'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
README_FILE = os.path.join(DATA_DIR, '配置文件说明.txt')  # 将说明文件名也定义为常量
SITE_TAG_PREFIX = "站点/"

CONFIG_README_CONTENT = """config.json 配置文件说明

{
    1. qbittorrent 连接信息
    "qbittorrent": {
        "host": "192.168.1.100:8080",
        "password": "",
        "username": ""
    },
    
    2. 当种子注释只有种子 id 没有完整的链接时，可以使用此规则来生成完整的链接
    "site_link_rules": {
        "一站": {
            "base_url": "https://a.com/detail/"
        }
    },
    
    3. 合并有多个 Tracker 的站点打标签出现的多个名称(如 站点/一站 与 站点/a 是同一个站点)
    "site_alias_mapping": {
        "a": "一站",
        "b": "二站"
    },
    
    4. 前端界面上的筛选设置，由程序自动管理，无需手动修改
    "ui_settings": {
        "active_path_filters": []
    }
}
"""

DEFAULT_SETTINGS = {
    "site_link_rules": {},
    "site_alias_mapping": {},
    "ui_settings": {
        "active_path_filters": []
    }
}


def save_config(config_data):
    """将配置字典保存到 config.json 文件"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)


# --- 应用启动初始化函数 ---
def initialize_app_files():
    """
    在应用启动时执行，独立检查并创建缺失的配置文件和说明文件
    """
    # 1. 独立检查并创建说明文件
    if not os.path.exists(README_FILE):
        print(f"说明文件不存在，正在创建: {README_FILE}")
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(README_FILE, 'w', encoding='utf-8') as f:
            f.write(CONFIG_README_CONTENT)

    # 2. 独立检查并创建配置文件
    if not os.path.exists(CONFIG_FILE):
        print(f"配置文件不存在，将尝试从环境变量创建: {CONFIG_FILE}")

        # 严格检查环境变量
        qb_host = os.environ.get('QB_HOST')
        qb_user = os.environ.get('QB_USERNAME')
        qb_pass = os.environ.get('QB_PASSWORD')

        if not all([qb_host, qb_user, qb_pass]):
            # 如果缺少环境变量，抛出异常，阻止应用不完整地启动
            raise ValueError("创建配置文件失败！请提供以下所有环境变量: "
                             "QB_HOST, QB_USERNAME, QB_PASSWORD")

        # 构建新的配置字典
        new_config = {
            "qbittorrent": {
                "host": qb_host,
                "username": qb_user,
                "password": qb_pass
            }
        }
        new_config.update(DEFAULT_SETTINGS)

        # 保存新配置
        save_config(new_config)
        print("成功生成新配置。")


def load_config():
    """
    加载配置文件。
    """
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"配置文件 {CONFIG_FILE} 未找到！应用初始化可能失败。")

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            if 'site_alias_mapping' not in config:
                config['site_alias_mapping'] = DEFAULT_SETTINGS[
                    'site_alias_mapping']
                save_config(config)
            return config
    except json.JSONDecodeError:
        raise ValueError(f"配置文件 {CONFIG_FILE} 格式错误，请检查是否为有效的 JSON。")


# --- 在应用启动时立即执行初始化 ---
initialize_app_files()


# --- 辅助函数 ---
def format_bytes(size_bytes):
    """
    格式化字符串(如"1.23 GB")
    """
    if size_bytes == 0: return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"


def format_state(state):
    """
    将qBittorrent状态转换为中文描述
    """
    s_lower = state.lower()
    if 'downloading' in s_lower: return '下载中'
    if 'uploading' in s_lower or 'stalledup' in s_lower: return '做种中'
    if 'paused' in s_lower or 'stopped' in s_lower or 'stalleddl' in s_lower:
        return '暂停'
    if 'checking' in s_lower: return '校验中'
    if 'error' in s_lower: return '错误'
    if 'missingfiles' in s_lower: return '文件丢失'
    return state.capitalize()


# --- 核心数据获取函数 ---
def get_torrent_data(config, path_filters=None, status_filters=None):
    results = {
        "data": [],
        "unique_paths": [],
        "unique_states": [],
        "all_discovered_sites": [],
        "site_link_rules": config.get('site_link_rules', {}),
        "error": None
    }
    qb_config = config.get('qbittorrent', {})
    alias_mapping = config.get('site_alias_mapping', {})

    try:
        qbt_client = Client(host=qb_config.get('host'),
                            username=qb_config.get('username'),
                            password=qb_config.get('password'))
        qbt_client.auth_log_in()
    except Exception as e:
        results["error"] = f"无法连接到qBittorrent。请检查配置。错误: {e}"
        return results

    try:
        torrents = qbt_client.torrents_info(status_filter='all')
    except Exception as e:
        results["error"] = f"获取种子列表失败。错误: {e}"
        return results

    if not torrents:
        return results

    # 提取所有唯一的保存路径和状态
    results["unique_paths"] = sorted(list({t.save_path for t in torrents}))
    all_details_for_state = [{
        'state': format_state(t.state)
    } for t in torrents]
    results["unique_states"] = sorted(
        list({d['state']
              for d in all_details_for_state}))

    master_site_list = set()
    for torrent in torrents:
        tags = [t.strip()
                for t in torrent.tags.split(',')] if torrent.tags else []
        for tag in tags:
            if tag.startswith(SITE_TAG_PREFIX):
                original_site_name = tag.split('/')[-1]
                site_name = alias_mapping.get(original_site_name,
                                              original_site_name)
                if site_name:
                    master_site_list.add(site_name)

    results["all_discovered_sites"] = sorted(list(master_site_list))

    processed_torrents = collections.defaultdict(dict)
    torrent_details = {}

    for torrent in torrents:
        details = {
            'save_path': torrent.save_path,
            'size': torrent.size,
            'size_formatted': format_bytes(torrent.size),
            'state': format_state(torrent.state),
            'progress': round(torrent.progress * 100, 1),
            'comment': torrent.comment
        }
        torrent_details[torrent.name] = details

        if path_filters and details['save_path'] not in path_filters: continue
        if status_filters and details['state'] not in status_filters: continue

        tags = [t.strip()
                for t in torrent.tags.split(',')] if torrent.tags else []
        for tag in tags:
            if tag.startswith(SITE_TAG_PREFIX):
                original_site_name = tag.split('/')[-1]
                site_name = alias_mapping.get(original_site_name,
                                              original_site_name)
                if site_name:
                    processed_torrents[
                        torrent.name][site_name] = torrent.comment or ""

    if not processed_torrents and (path_filters or status_filters):
        results["error"] = "在选定的筛选条件下，未找到任何带 '站点/...' 标签的种子。"
    elif not all(t for t in torrents if any(
            tag.startswith(SITE_TAG_PREFIX)
            for tag in (t.tags.split(',') if t.tags else []))):
        if not master_site_list:
            results["error"] = "未找到任何带 '站点/...' 标签的种子。"

    data_list = []
    for name, sites_with_comments in sorted(processed_torrents.items()):
        details = torrent_details.get(name, {})
        data_list.append({
            "name": name,
            "sites": sites_with_comments,
            "save_path": details.get('save_path', 'N/A'),
            "size": details.get('size', 0),
            "size_formatted": details.get('size_formatted', 'N/A'),
            "state": details.get('state', 'N/A'),
            "progress": details.get('progress', 0)
        })
    results["data"] = data_list
    return results


# --- Flask 路由 ---
@app.route('/')
def index_page():
    return render_template('index.html')


@app.route('/api/data')
def get_data_api():
    """
    获取种子数据API
    
    查询参数:
        path_filter: 路径筛选条件(可选)
        status_filter: 状态筛选条件(可选)
        
    返回:
        JSON格式的种子数据
    """
    try:
        config = load_config()
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 500

    path_filters = request.args.getlist('path_filter')
    status_filters = request.args.getlist('status_filter')
    context = get_torrent_data(config,
                               path_filters=path_filters,
                               status_filters=status_filters)
    if 'ui_settings' in config and 'active_path_filters' in config[
            'ui_settings']:
        context['active_path_filters'] = config['ui_settings'][
            'active_path_filters']
    else:
        context['active_path_filters'] = []

    return jsonify(context)


@app.route('/api/save_filters', methods=['POST'])
def save_filters_api():
    """
    保存路径筛选设置API
    
    请求体:
        JSON格式,包含paths字段
        
    返回:
        JSON格式的操作结果消息
    """
    data = request.get_json()
    if data is None or 'paths' not in data:
        return jsonify({"error": "无效的请求"}), 400
    config = load_config()
    if 'ui_settings' not in config:
        config['ui_settings'] = {}
    config['ui_settings']['active_path_filters'] = data['paths']
    save_config(config)
    return jsonify({"message": "筛选器设置已保存"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
