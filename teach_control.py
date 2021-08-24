import json
import os
import re
import shutil
from typing import List
from urllib.parse import urljoin

import pathvalidate
import requests
from bs4 import BeautifulSoup
from pytube import YouTube

download_dir = 'download/'
cache_dir = 'cache/'
root_url = 'https://vozhdenium.com/teach/control'

# Copy from devtool in browser
# like:
# {
#   "chtm-token": "...",
#   "dd_bdfhyr": "...",
#   "gc_visitor_42486": "{\"id\":...}",
#   "PHPSESSID5": "..."
# }
with open('cookies.json') as file:
    cookies = json.load(file)


# try:
#     import http.client as http_client
# except ImportError:
#     # Python 2
#     import httplib as http_client
# http_client.HTTPConnection.debuglevel = 1
#
# # You must initialize logging, otherwise you'll not see debug output.
# logging.basicConfig()
# logging.getLogger().setLevel(logging.DEBUG)
# requests_log = logging.getLogger("requests.packages.urllib3")
# requests_log.setLevel(logging.DEBUG)
# requests_log.propagate = True


def sanitize_filename(name: str) -> str:
    return pathvalidate.sanitize_filename(name.strip())[:100]


def load_content_from_internet(url: str, headers=None):
    response = requests.get(url, headers=headers, cookies=cookies)
    code = response.status_code
    print(code, url)
    if code == 200:
        return response.text
    return None


def load_content_from_local(cache_path):
    with open(cache_path, 'r', encoding='utf-8') as f:
        return f.read()


def save_text_content_to_local(cache_path, content):
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        f.write(content)


def download_content_and_save_to_file(url: str, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = requests.get(url, stream=True, cookies=cookies)
    if r.status_code == 200:
        with open(path, 'wb') as f:
            r.raw.decode_content = True
            shutil.copyfileobj(r.raw, f)
    r.raise_for_status()


def download_content_and_save_to_file_if_not_cached(url: str, path: str):
    if os.path.exists(path):
        return
    tmp_path = f'{path}.tmp_'
    print(f'downloading {url} to {path}')
    try:
        download_content_and_save_to_file(url, tmp_path)
        os.rename(tmp_path, path)
    except Exception as e:
        print(e)


def extract_path_from_url(url: str) -> str:
    """
    convert url like: https://glavuch.ru/pl/teach/control/lesson/view?id=172392721
    in path like: glavuch.ru/pl/teach/control/lesson/view/id_172392721.html
    """
    match = re.match(r'\w+://(.+)', url)
    if match is None:
        return url
    sub_url = match.group(1)
    if '?' in sub_url:
        split = sub_url.split('?', 2)
        dir_path = split[0]
        file_name = split[1].replace('=', '_')
        return f'{dir_path}/{file_name}.html'
    return f'{sub_url}.html'


def get_content(url: str, headers=None):
    if url is None:
        return
    cache_path = f"{cache_dir}{extract_path_from_url(url)}"
    if os.path.exists(cache_path):
        return load_content_from_local(cache_path)
    content = load_content_from_internet(url, headers)
    if content is not None:
        save_text_content_to_local(cache_path, content)
    return content


def clear_url(url: str) -> str:
    return url.split('?', 1)[0]


def get_module_header(content: str) -> str:
    soup = BeautifulSoup(content, 'html.parser')
    lesson_header = soup.find(class_='lesson-title-value') or soup.find('title')
    if lesson_header:
        return lesson_header.text
    page_header = soup.find('div', class_='page-header').find('a')
    return page_header.text


def add_scheme(url: str) -> str:
    if url.startswith('http'):
        return url
    return 'https:' + url


def get_all_video_src(content: str) -> List[dict]:
    soup = BeautifulSoup(content, 'html.parser')
    items = soup.find_all('iframe')
    stream = map(
        lambda item: {'type': 'video_src', 'url': clear_url(add_scheme(item.get('src'))),
                      'sourceline': item.sourceline},
        items)
    return list(stream)


def get_all_headers(content: str) -> List[dict]:
    soup = BeautifulSoup(content, 'html.parser')
    items = soup.find_all('div')
    stream = list(map(lambda x: x.find_all('p'), items))
    stream = list(filter(lambda x: len(x) == 1, stream))
    stream = list(map(lambda x: x[0], stream))
    stream = list(map(lambda x: {'type': 'header', 'text': x.text.strip(), 'sourceline': x.sourceline}, stream))
    return list(stream)


def get_module_files(content: str) -> List[dict]:
    soup = BeautifulSoup(content, 'html.parser')
    files_block = soup.find_all('div', class_='lt-lesson-files')
    stream = map(lambda x: x.find_all('a'), files_block)
    stream = sum(stream,
                 [])  # https://stackoverflow.com/questions/952914/how-to-make-a-flat-list-out-of-list-of-lists#952946
    stream = map(lambda x: {'type': 'file', 'text': x.text.strip(), 'url': x.get('href'), 'sourceline': x.sourceline},
                 stream)
    return list(stream)


def get_direct_url_from_youtube(url: str):
    return YouTube(url).streams.get_highest_resolution().url


def get_direct_url_from_vimeo(content: str):
    config_begin = 'var config = '
    config_end = '; if'
    start_index = content.find(config_begin) + len(config_begin)
    end_index = content.find(config_end, start_index)
    config_str = content[start_index:end_index]
    config_dict = json.loads(config_str)
    progressive_variants = config_dict['request']['files']['progressive']
    best_quality = max(progressive_variants, key=lambda x: x['height'])
    return best_quality['url']


def get_video_info_list(content: str) -> list:
    all_video_src = get_all_video_src(content)
    all_headers = get_all_headers(content)
    all_headers.sort(key=lambda x: x['sourceline'])
    result = []
    for index, video_src in enumerate(all_video_src):
        near_header = \
            (list(filter(lambda header: header['sourceline'] < video_src['sourceline'], all_headers)) or [None])[-1]
        title = (near_header and near_header['text'])
        unique_title = f"{index}_{title}" if title else f"{index}"
        headers = {'Referer': 'https://vozhdenium.com/'}
        video_url = video_src['url']
        if 'vimeo' in video_url:
            video_direct_url = get_direct_url_from_vimeo(get_content(video_url, headers))
            result.append({'header': unique_title, 'url': video_direct_url})
        elif 'youtube' in video_url:
            video_direct_url = get_direct_url_from_youtube(video_url)
            result.append({'header': unique_title, 'url': video_direct_url})
    return result


def download_video(directory: str, video_info: dict):
    url = video_info['url']
    file_name = sanitize_filename(video_info['header'])
    path = f'{directory}/{file_name}.mp4'
    download_content_and_save_to_file_if_not_cached(url, path)


def download_file(directory: str, file_info: dict):
    url = file_info['url']
    file_name = sanitize_filename(file_info['text'])
    ext = os.path.splitext(url)[1]
    path = f'{directory}/{file_name}{ext}'
    download_content_and_save_to_file_if_not_cached(url, path)


def download_module(url: str, content: str, base_dir: str):
    module_header = get_module_header(content)
    files = get_module_files(content)
    video_info_list = get_video_info_list(content)

    module_path_name = sanitize_filename(module_header)
    module_dir = base_dir if base_dir.endswith(module_path_name + '/') else (base_dir + module_path_name)
    for video_info in video_info_list:
        download_video(module_dir, video_info)
    if len(files) > 0:
        files_dir = f'{module_dir}/files'
        for file_info in files:
            download_file(files_dir, file_info)


def get_title(content: str):
    soup = BeautifulSoup(content, 'html.parser')
    return soup.find('title').text


def download_teach_control(url: str):
    content = get_content(url)
    title = get_title(content)


def get_content_type(content: str):
    if 'stream-title' in content:
        return 'catalog1'
    if 'link title' in content:
        return 'catalog2'
    if 'videoWrapper' in content:
        return 'module'
    return None


def get_element_text(element):
    if element is not None:
        return element.text
    return None


def normalize_url(base_url, url):
    return urljoin(base_url, url)


def download_catalog1(url: str, content: str, base_dir: str = ''):
    soup = BeautifulSoup(content, 'html.parser')
    a_list = soup.find_all('a')
    get_stream_title = lambda element: {'url': normalize_url(url, element.get('href')),
                                        'title': get_element_text(element.find('span', class_='stream-title'))}
    stream = map(get_stream_title, a_list)
    stream = filter(lambda x: x['title'] is not None, stream)
    for item in stream:
        smart(item['url'], f'{base_dir}{sanitize_filename(item["title"])}/')


def download_catalog2(url: str, content: str, base_dir: str = ''):
    soup = BeautifulSoup(content, 'html.parser')
    a_list = soup.find_all('div', class_='link title')
    get_stream_title = lambda element: {'url': normalize_url(url, element.get('href')), 'title': element.text}
    stream = map(get_stream_title, a_list)
    for item in stream:
        smart(item['url'], f'{base_dir}{sanitize_filename(item["title"])}/')


def fix_url(url):
    return re.sub(r'(.+)/id/(\d+)', r'\1?id=\2', url)


def smart(url: str, base_dir: str = ''):
    url = fix_url(url)
    content = get_content(url)
    if content is None:
        return
    content_type = get_content_type(content)
    if content_type == 'catalog1':
        download_catalog1(url, content, base_dir)
    if content_type == 'catalog2':
        download_catalog2(url, content, base_dir)
    if content_type == 'module':
        download_module(url, content, base_dir)


# load_content_from_internet("https://vozhdenium.com/teach/control/lesson/view/id/138739257")
# exit(0)

# download_module(example_url)
# download_teach_control('https://glavuch.ru/teach/control/stream/view/id/252290526')

smart(root_url, 'download/')
# smart('https://glavuch.ru/teach/control/lesson/view/id/173862505')
print('ready')
