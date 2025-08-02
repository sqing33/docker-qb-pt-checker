# app.py
import collections
import json
import os
import math
from functools import cmp_to_key
from flask import Flask, jsonify, render_template, request
from qbittorrentapi import Client
from transmission_rpc import Client as TrClient

app = Flask(__name__)
DATA_DIR = '/data'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
README_FILE = os.path.join(DATA_DIR, '配置文件说明.txt')
SITE_TAG_PREFIX = "站点/"

CONFIG_README_CONTENT = '''{
  "qbittorrent": {
    "enabled": true,
    "host": "192.168.1.100:8080",
    "username": "",
    "password": ""
  },
  "transmission": {
    "enabled": true,
    "host": "192.168.1.100",
    "port": 9091,
    "username": "",
    "password": ""
  },
  "site_link_rules": {
    "站点名称": {
      "base_url": "https://example.com/detail/"
    }
  },
  "site_alias_mapping": {
    "站点缩写": "站点全称",
    "another_short_name": "站点别名"
  },
  "ui_settings": {
    "active_path_filters": [],
    "active_downloader_filters": []
  }
}'''


def save_config(config_data):
    """
    保存配置到config.json文件
    参数:
        config_data: 要保存的配置字典
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)


def initialize_app_files():
    """
    初始化应用文件
    创建必要的配置文件和说明文件
    如果config.json不存在，会根据环境变量创建默认配置
    """
    if not os.path.exists(README_FILE):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(README_FILE, 'w', encoding='utf-8') as f:
            f.write("...")  # Readme content
    if not os.path.exists(CONFIG_FILE):
        config_data = {
            "qbittorrent": {
                "enabled": os.getenv("QB_HOST") is not None,
                "host": os.getenv("QB_HOST", "192.168.1.100:8080"),
                "username": os.getenv("QB_USERNAME", ""),
                "password": os.getenv("QB_PASSWORD", "")
            },
            "transmission": {
                "enabled": os.getenv("TR_HOST") is not None,
                "host": os.getenv("TR_HOST", "192.168.1.100"),
                "port": int(os.getenv("TR_PORT", "9091")),
                "username": os.getenv("TR_USERNAME", ""),
                "password": os.getenv("TR_PASSWORD", "")
            },
            "site_link_rules": {},
            "site_alias_mapping": {},
            "ui_settings": {
                "active_path_filters": [],
                "active_downloader_filters": []
            }
        }
        save_config(config_data)


def load_config():
    """
    从config.json加载配置
    返回:
        配置字典
    异常:
        FileNotFoundError: 配置文件不存在
        ValueError: 配置文件格式错误
    """
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"配置文件 {CONFIG_FILE} 未找到！应用初始化可能失败。")
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return config
    except json.JSONDecodeError:
        raise ValueError(f"配置文件 {CONFIG_FILE} 格式错误，请检查是否为有效的 JSON。")


initialize_app_files()


def format_bytes(size_bytes):
    """
    格式化字节大小为易读的字符串
    参数:
        size_bytes: 字节大小
    返回:
        格式化后的字符串(如"1.23 MB")
    """
    if size_bytes == 0: return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    try:
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"
    except (ValueError, IndexError):
        return "0 B"


def format_state(state):
    """
    格式化下载状态为中文描述
    参数:
        state: 原始状态字符串
    返回:
        中文状态描述
    """
    s_lower = state.lower()
    if 'downloading' in s_lower or 'meta' in s_lower: return '下载中'
    if 'uploading' in s_lower or 'stalledup' in s_lower or 'seed' in s_lower:
        return '做种中'
    if 'paused' in s_lower or 'stopped' in s_lower or 'stalleddl' in s_lower:
        return '暂停'
    if 'checking' in s_lower or 'check' in s_lower: return '校验中'
    if 'error' in s_lower: return '错误'
    if 'missingfiles' in s_lower: return '文件丢失'
    return state.capitalize()


def get_char_type(char):
    char = char.lower()
    if 'a' <= char <= 'z': return 1
    if '0' <= char <= '9': return 2
    return 3


def custom_sort_compare(item_a, item_b):
    name_a, name_b = item_a['name'].lower(), item_b['name'].lower()
    min_len = min(len(name_a), len(name_b))
    for i in range(min_len):
        type_a, type_b = get_char_type(name_a[i]), get_char_type(name_b[i])
        if type_a != type_b: return type_a - type_b
        if name_a[i] != name_b[i]: return -1 if name_a[i] < name_b[i] else 1
    return len(name_a) - len(name_b)


def get_torrent_data(config, path_filters=None, status_filters=None):
    """
    从qBittorrent获取种子数据
    参数:
        config: 应用配置
        path_filters: 路径过滤器列表
        status_filters: 状态过滤器列表
    返回:
        (种子数据列表, 错误信息)
    """
    qb_config = config.get('qbittorrent', {})
    alias_mapping = config.get('site_alias_mapping', {})
    if not qb_config.get('enabled', True):
        return [], None  # 禁用时不返回错误信息
    if not qb_config.get('host'):
        return [], "qBittorrent Host 未配置，已跳过。"
    try:
        # 过滤掉enabled参数
        client_config = {k: v for k, v in qb_config.items() if k != 'enabled'}
        qbt_client = Client(**client_config)
        qbt_client.auth_log_in()
    except Exception as e:
        return [], f"无法连接到qBittorrent: {e}"
    try:
        torrents = qbt_client.torrents_info(status_filter='all')
    except Exception as e:
        return [], f"从 qBittorrent 获取种子列表失败: {e}"
    processed_torrents = collections.defaultdict(dict)
    torrent_details = {}
    for torrent in torrents:
        formatted_state = format_state(torrent.state)
        if path_filters and torrent.save_path not in path_filters: continue
        if status_filters and formatted_state not in status_filters: continue
        if torrent.name not in torrent_details:
            torrent_details[torrent.name] = {
                "save_path": torrent.save_path,
                "size": torrent.size,
                "size_formatted": format_bytes(torrent.size),
                "state": formatted_state,
                "progress": round(torrent.progress * 100, 1),
                "downloader": "qbittorrent"
            }
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
    data_list = []
    for name, sites in processed_torrents.items():
        if name in torrent_details:
            details = torrent_details[name]
            details['name'] = name
            details['sites'] = sites
            data_list.append(details)
    return data_list, None


def get_tr_torrent_data(config, path_filters=None, status_filters=None):
    """
    从Transmission获取种子数据
    参数:
        config: 应用配置
        path_filters: 路径过滤器列表
        status_filters: 状态过滤器列表
    返回:
        (种子数据列表, 错误信息)
    """
    tr_config = config.get('transmission', {})
    alias_mapping = config.get('site_alias_mapping', {})
    if not tr_config.get('enabled', True):
        return [], None  # 禁用时不返回错误信息
    if not tr_config.get('host'):
        return [], "Transmission Host 未配置，已跳过。"
    try:
        # 过滤掉enabled参数
        client_config = {k: v for k, v in tr_config.items() if k != 'enabled'}
        tr_client = TrClient(**client_config)
    except Exception as e:
        return [], f"无法连接到Transmission: {e}"
    try:
        torrents = tr_client.get_torrents()
    except Exception as e:
        return [], f"从 Transmission 获取种子列表失败: {e}"
    processed_torrents = collections.defaultdict(dict)
    torrent_details = {}
    for torrent in torrents:
        formatted_state = format_state(torrent.status)
        if path_filters and torrent.download_dir not in path_filters: continue
        if status_filters and formatted_state not in status_filters: continue
        if torrent.name not in torrent_details:
            torrent_details[torrent.name] = {
                "save_path": torrent.download_dir,
                "size": torrent.total_size,
                "size_formatted": format_bytes(torrent.total_size),
                "state": formatted_state,
                "progress": round(torrent.progress, 1),
                "downloader": "transmission"
            }
        tags = [t.strip() for t in (torrent.labels or [])]
        for tag in tags:
            if tag.startswith(SITE_TAG_PREFIX):
                original_site_name = tag.split('/')[-1]
                site_name = alias_mapping.get(original_site_name,
                                              original_site_name)
                if site_name:
                    processed_torrents[
                        torrent.name][site_name] = torrent.comment if hasattr(
                            torrent, 'comment') else ""
    data_list = []
    for name, sites in processed_torrents.items():
        if name in torrent_details:
            details = torrent_details[name]
            details['name'] = name
            details['sites'] = sites
            data_list.append(details)
    return data_list, None


def get_all_torrents_metadata(config):
    """
    获取所有种子的元数据(路径、状态、站点)
    参数:
        config: 应用配置
    返回:
        (唯一路径列表, 唯一状态列表, 所有站点列表)
    """
    all_unique_paths, all_unique_states, all_sites = set(), set(), set()
    alias_mapping = config.get('site_alias_mapping', {})
    qb_config = config.get('qbittorrent', {})
    if qb_config.get('enabled', True) and qb_config.get('host'):
        try:
            client_config = {
                k: v
                for k, v in qb_config.items() if k != 'enabled'
            }
            qbt_client = Client(**client_config)
            qbt_client.auth_log_in()
            torrents = qbt_client.torrents_info(status_filter='all')
            all_unique_paths.update(t.save_path for t in torrents)
            all_unique_states.update(format_state(t.state) for t in torrents)
            for t in torrents:
                tags = [tag.strip()
                        for tag in t.tags.split(',')] if t.tags else []
                for tag in tags:
                    if tag.startswith(SITE_TAG_PREFIX):
                        original = tag.split('/')[-1]
                        all_sites.add(alias_mapping.get(original, original))
        except Exception:
            pass
    tr_config = config.get('transmission', {})
    if tr_config.get('enabled', True) and tr_config.get('host'):
        try:
            client_config = {
                k: v
                for k, v in tr_config.items() if k != 'enabled'
            }
            tr_client = TrClient(**client_config)
            torrents = tr_client.get_torrents()
            all_unique_paths.update(t.download_dir for t in torrents)
            all_unique_states.update(format_state(t.status) for t in torrents)
            for t in torrents:
                tags = [tag.strip() for tag in (t.labels or [])]
                for tag in tags:
                    if tag.startswith(SITE_TAG_PREFIX):
                        original = tag.split('/')[-1]
                        all_sites.add(alias_mapping.get(original, original))
        except Exception:
            pass
    return sorted(list(all_unique_paths)), sorted(
        list(all_unique_states)), sorted(list(all_sites))


# --- Flask 路由 ---
@app.route('/')
def index_page():
    return render_template('index.html')


@app.route('/api/data')
def get_data_api():
    """
    获取种子数据API
    返回:
        JSON格式的种子数据和筛选选项
    """
    try:
        config = load_config()
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 500

    path_filters = request.args.getlist('path_filter')
    status_filters = request.args.getlist('status_filter')
    downloader_filters = request.args.getlist('downloader_filter')

    merged_torrents, error_msgs = {}, []
    downloader_funcs = []

    qb_enabled = config.get('qbittorrent', {}).get('enabled', True)
    tr_enabled = config.get('transmission', {}).get('enabled', True)

    # 如果没有指定下载器筛选，则默认使用所有已启用的下载器
    if not downloader_filters:
        if qb_enabled:
            downloader_filters.append('qbittorrent')
        if tr_enabled:
            downloader_filters.append('transmission')

    if 'qbittorrent' in downloader_filters and qb_enabled:
        downloader_funcs.append(get_torrent_data)
    if 'transmission' in downloader_filters and tr_enabled:
        downloader_funcs.append(get_tr_torrent_data)

    for func in downloader_funcs:
        data_list, error = func(config, path_filters, status_filters)
        if error:
            error_msgs.append(
                f"{func.__name__.replace('get_','').replace('_torrent_data','')}: {error}"
            )
        for item in data_list:
            name = item['name']
            if name not in merged_torrents:
                merged_torrents[name] = item
            else:
                merged_torrents[name]['sites'].update(item['sites'])
                downloader_str = merged_torrents[name]['downloader']
                if item['downloader'] not in downloader_str:
                    merged_torrents[name][
                        'downloader'] += f", {item['downloader']}"

    all_data = list(merged_torrents.values())
    unique_paths, unique_states, all_discovered_sites = get_all_torrents_metadata(
        config)
    final_error = '\n'.join(error_msgs) if error_msgs else None

    sorted_data = sorted(all_data, key=cmp_to_key(custom_sort_compare))

    ui_settings = config.get('ui_settings', {})
    return jsonify({
        'data':
        sorted_data,
        'unique_paths':
        unique_paths,
        'unique_states':
        unique_states,
        'all_discovered_sites':
        all_discovered_sites,
        'site_link_rules':
        config.get('site_link_rules', {}),
        'active_path_filters':
        ui_settings.get('active_path_filters', []),
        'active_downloader_filters':
        ui_settings.get('active_downloader_filters', []),
        'error':
        final_error
    })


@app.route('/api/save_filters', methods=['POST'])
def save_filters_api():
    """
    保存筛选设置API
    """
    data = request.get_json()
    if data is None:
        return jsonify({"error": "无效的请求"}), 400
    try:
        config = load_config()
        if 'ui_settings' not in config:
            config['ui_settings'] = {}
        if 'paths' in data:
            config['ui_settings']['active_path_filters'] = data['paths']
        if 'downloaders' in data:
            config['ui_settings']['active_downloader_filters'] = data[
                'downloaders']
        save_config(config)
        return jsonify({"message": "筛选器设置已保存"})
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/downloader_info')
def get_downloader_info_api():
    """
    获取下载器客户端的实时信息API
    """
    config = load_config()
    info = {
        'qbittorrent': {
            'enabled': False,
            'status': '未配置',
            'details': {}
        },
        'transmission': {
            'enabled': False,
            'status': '未配置',
            'details': {}
        }
    }

    # 获取 qBittorrent 信息
    qb_config = config.get('qbittorrent', {})
    info['qbittorrent']['enabled'] = qb_config.get('enabled', True)
    if info['qbittorrent']['enabled']:
        try:
            client_config = {
                k: v
                for k, v in qb_config.items() if k != 'enabled'
            }
            qbt_client = Client(**client_config)
            qbt_client.auth_log_in()
            app_info = qbt_client.app
            transfer_info = qbt_client.transfer_info
            info['qbittorrent']['status'] = '已连接'
            info['qbittorrent']['details'] = {
                '版本': app_info.version,
                'Web API 版本': app_info.api_version,
                '总下载速度': f"{format_bytes(transfer_info.dl_info_speed)}/s",
                '总上传速度': f"{format_bytes(transfer_info.up_info_speed)}/s",
                '磁盘剩余空间': format_bytes(app_info.free_space_on_disk),
            }
        except Exception as e:
            info['qbittorrent']['status'] = '连接失败'
            info['qbittorrent']['details'] = {'错误信息': str(e)}

    # 获取 Transmission 信息
    tr_config = config.get('transmission', {})
    info['transmission']['enabled'] = tr_config.get('enabled', True)
    if info['transmission']['enabled']:
        try:
            client_config = {
                k: v
                for k, v in tr_config.items() if k != 'enabled'
            }
            tr_client = TrClient(**client_config)
            stats = tr_client.session_stats()
            info['transmission']['status'] = '已连接'
            info['transmission']['details'] = {
                '版本': tr_client.server_version,
                'RPC 版本': str(tr_client.rpc_version),
                '总下载速度': f"{format_bytes(stats.download_speed)}/s",
                '总上传速度': f"{format_bytes(stats.upload_speed)}/s",
            }
        except Exception as e:
            info['transmission']['status'] = '连接失败'
            info['transmission']['details'] = {'错误信息': str(e)}

    return jsonify(info)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
