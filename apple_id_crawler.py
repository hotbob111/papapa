"""
远程公开页列表同步 - 集成版
从配置的公开 HTML 页面拉取并解析列表项，合并去重后写入 JSON，可选 POST 到网站后台。
"""

import os
import requests
import cloudscraper
from bs4 import BeautifulSoup
import json
import re
import time
from typing import List, Dict, Optional
from datetime import datetime
from urllib.parse import urlparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RemoteFeedClient:
    """远程列表拉取客户端 - 可选同步网站后台 API"""
    
    # 顺序决定合并后展示顺序：靠前的来源先写入列表；去重时保留先出现的记录
    # TK 在前 → TK 账号排在前面，且两站重复邮箱时保留 TK 页数据
    DEFAULT_SOURCE_URLS = [
        "https://tkbaohe.com/Shadowrocket/",
        "https://ccbaohe.com/appleID/",
    ]
    
    @staticmethod
    def _is_brand_region_text(text: str) -> bool:
        """【】内若为站点品牌说明，不应当作地区"""
        if not text:
            return False
        t = text.strip()
        tl = t.lower()
        return (
            "CC宝盒" in t or "TK宝盒" in t
            or "ccbaohe" in tl or "tkbaohe" in tl
        )
    
    def __init__(self, api_url: str = None, source_urls: Optional[List[str]] = None):
        """
        初始化客户端
        
        Args:
            api_url: 网站后台 API 地址（如 data_sync.php 的 URL）
            source_urls: 要拉取的页面 URL 列表。也可用环境变量 SOURCE_URLS 或 CRAWLER_URLS（英文逗号分隔）覆盖；优先 SOURCE_URLS。
        """
        env_urls = (
            os.environ.get("SOURCE_URLS", "").strip()
            or os.environ.get("CRAWLER_URLS", "").strip()
        )
        if env_urls:
            self.source_urls = [u.strip() for u in env_urls.split(",") if u.strip()]
        elif source_urls:
            self.source_urls = list(source_urls)
        else:
            self.source_urls = list(self.DEFAULT_SOURCE_URLS)
        
        self.base_url = self.source_urls[0]
        self.api_url = api_url  # 例如: "http://your-domain.com/data_sync.php"
        
        # 使用 cloudscraper 构建更接近浏览器的 HTTP 会话（兼容常见站点防护响应；依赖名不可改）
        try:
            # 尝试多种浏览器指纹配置
            browser_configs = [
                {
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True
                },
                {
                    'browser': 'firefox',
                    'platform': 'windows',
                    'desktop': True
                },
                {
                    'browser': 'chrome',
                    'platform': 'linux',
                    'desktop': True
                }
            ]
            
            self.session = None
            for config in browser_configs:
                try:
                    self.session = cloudscraper.create_scraper(browser=config)
                    logger.info(f"✅ 已创建兼容型 HTTP 会话（配置: {config['browser']}）")
                    break
                except:
                    continue
            
            if not self.session:
                # 如果所有配置都失败，使用默认配置
                self.session = cloudscraper.create_scraper()
                logger.info("✅ 已使用默认配置创建兼容型 HTTP 会话")
        except Exception as e:
            logger.warning(f"⚠️ 会话组件初始化失败，回退到 requests: {e}")
            self.session = requests.Session()
        
        self._default_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'Referer': 'https://ccbaohe.com/',
            'DNT': '1'
        }
        self.session.headers.update(self._default_headers)
        
        self.accounts = []
    
    def fetch_page(self, url: Optional[str] = None) -> Optional[BeautifulSoup]:
        """获取网页内容"""
        target = url or self.base_url
        try:
            parsed = urlparse(target)
            origin = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else "https://ccbaohe.com/"
            self.session.headers["Referer"] = origin
            
            logger.info(f"正在访问: {target}")
            
            # 添加延迟，模拟人类行为
            time.sleep(2)
            
            # 先访问同站主页，建立会话
            try:
                self.session.get(origin, timeout=15)
                time.sleep(1)
            except Exception:
                pass
            
            # 访问目标页面
            response = self.session.get(target, timeout=30, allow_redirects=True)
            response.raise_for_status()
            
            # 检查响应头，看看是否被压缩
            content_encoding = response.headers.get('Content-Encoding', '').lower()
            logger.info(f"响应Content-Encoding: {content_encoding}")
            logger.info(f"响应Content-Type: {response.headers.get('Content-Type', '未知')}")
            
            # 如果响应被压缩但未自动解压，手动解压
            # 注意：如果响应内容已经是乱码，可能是压缩数据没有被正确解压
            if content_encoding:
                import gzip
                try:
                    import brotli
                except ImportError:
                    brotli = None
                
                try:
                    if 'gzip' in content_encoding:
                        logger.info("检测到gzip压缩，尝试手动解压...")
                        decompressed = gzip.decompress(response.content)
                        response._content = decompressed
                        response._content_consumed = True
                        logger.info(f"✅ gzip解压成功，解压后长度: {len(decompressed)} 字节")
                    elif ('br' in content_encoding or 'brotli' in content_encoding) and brotli:
                        logger.info("检测到brotli压缩，尝试手动解压...")
                        decompressed = brotli.decompress(response.content)
                        response._content = decompressed
                        response._content_consumed = True
                        logger.info(f"✅ brotli解压成功，解压后长度: {len(decompressed)} 字节")
                    elif 'deflate' in content_encoding:
                        import zlib
                        logger.info("检测到deflate压缩，尝试手动解压...")
                        decompressed = zlib.decompress(response.content)
                        response._content = decompressed
                        response._content_consumed = True
                        logger.info(f"✅ deflate解压成功，解压后长度: {len(decompressed)} 字节")
                except Exception as e:
                    logger.warning(f"解压失败: {e}，尝试使用原始内容")
            
            # 如果响应内容看起来是乱码（不包含HTML标签），尝试自动检测并解压
            raw_content = response.content
            if not response.text or '<html' not in response.text.lower() and '<body' not in response.text.lower():
                logger.warning("响应内容不包含HTML标签，可能是压缩数据，尝试自动解压...")
                # 尝试gzip
                try:
                    import gzip
                    decompressed = gzip.decompress(raw_content)
                    if '<html' in decompressed.decode('utf-8', errors='ignore').lower():
                        logger.info("✅ 通过gzip自动解压成功！")
                        response._content = decompressed
                        response._content_consumed = True
                except:
                    pass
                
                # 如果gzip失败，尝试brotli
                if '<html' not in response.text.lower():
                    try:
                        import brotli
                        decompressed = brotli.decompress(raw_content)
                        if '<html' in decompressed.decode('utf-8', errors='ignore').lower():
                            logger.info("✅ 通过brotli自动解压成功！")
                            response._content = decompressed
                            response._content_consumed = True
                    except:
                        pass
            
            # 确保使用UTF-8编码
            if response.encoding.lower() not in ['utf-8', 'utf8']:
                response.encoding = 'utf-8'
            
            # 检查响应内容是否可读（是否包含HTML标签）
            if not response.text or len(response.text) < 100:
                logger.error("响应内容为空或过短")
                return None
            
            # 调试信息：检查响应内容
            logger.info(f"响应状态码: {response.status_code}")
            logger.info(f"响应内容长度: {len(response.text)} 字符")
            
            # 检查是否包含card元素的关键词
            if 'card' in response.text.lower():
                logger.info("✅ 响应中包含'card'关键词")
            else:
                logger.warning("⚠️ 响应中未找到'card'关键词")
            
            # 检查是否被重定向或返回错误页面
            if len(response.text) < 1000:
                logger.warning(f"⚠️ 响应内容过短（{len(response.text)}字符），可能是错误页面")
                logger.info(f"响应内容预览: {response.text[:500]}")
            
            # 检测响应中是否含常见站点防护/人机校验特征（以下为正文子串，勿改字面量）
            cf_indicators = [
                'challenge-platform',
                'cf-browser-verification',
                'just a moment',
                'checking your browser',
                'ddos protection',
                'cf-ray',
                'cloudflare',
                '__cf_bm',
                'cf_clearance'
            ]
            
            is_cf_challenge = any(indicator in response.text.lower() for indicator in cf_indicators)
            
            if is_cf_challenge:
                logger.error("❌ 检测到疑似站点防护/人机校验页（响应中含防护特征）")
                logger.error("完整内容可能依赖脚本渲染，纯 HTTP 客户端可能无法继续")
                
                # 尝试保存完整响应用于分析
                try:
                    with open('cf_challenge_response.html', 'w', encoding='utf-8') as f:
                        f.write(response.text)
                    logger.info("已保存校验页快照到 cf_challenge_response.html（调试用）")
                except:
                    pass
                
                # 如果响应很短，可能是重定向或错误页面
                if len(response.text) < 5000:
                    logger.warning("响应内容过短，可能是被拦截")
                    # 不直接返回None，继续尝试解析
                else:
                    # 如果响应很长但没有card，可能是JavaScript渲染的内容
                    logger.warning("⚠️ 响应内容可能需要在浏览器中渲染JavaScript才能看到真实内容")
                    logger.warning("建议：使用无头浏览器类工具渲染页面后再解析")
            
            # 检查是否包含常见的HTML结构
            has_html = '<html' in response.text.lower() or '<body' in response.text.lower()
            has_div = '<div' in response.text.lower()
            has_script = '<script' in response.text.lower()
            logger.info(f"响应包含HTML标签: {has_html}, 包含div标签: {has_div}, 包含script标签: {has_script}")
            
            # 如果包含大量JavaScript但没有div，可能是需要渲染的页面
            if has_script and not has_div and len(response.text) > 5000:
                logger.warning("⚠️ 响应包含大量JavaScript但缺少HTML结构，可能需要浏览器渲染")
                logger.warning("响应内容前1000字符:")
                logger.warning(response.text[:1000])
            
            # 如果响应内容很短，输出更多信息
            if len(response.text) < 5000:
                logger.warning(f"⚠️ 响应内容较短，完整内容:")
                logger.info(response.text)
            
            # 保存实际返回的HTML内容到文件（用于调试）
            try:
                with open('debug_response.html', 'w', encoding='utf-8') as f:
                    f.write(response.text)
                logger.info("✅ 已保存响应内容到 debug_response.html（用于调试）")
            except:
                pass
            
            # 检查响应内容的前500字符，看看实际返回了什么
            response_preview = response.text[:500]
            logger.info(f"响应内容前500字符预览:")
            logger.info(response_preview)
            
            # 强校验：含以下子串则判定为拦截页并中止（字面量勿改）
            if 'challenge-platform' in response.text.lower() or 'cf-browser-verification' in response.text.lower() or 'just a moment' in response.text.lower():
                logger.error("❌ 判定为站点防护拦截页，当前环境无法继续解析（常见于 CI 无浏览器）")
                logger.error("可尝试：无头浏览器、代理或更换出口网络")
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 尝试多种方式查找card元素
            cards_by_class = soup.find_all('div', class_='card')
            cards_by_style = soup.find_all('div', class_='card', attrs={'style': True})
            logger.info(f"通过class='card'找到 {len(cards_by_class)} 个元素")
            logger.info(f"通过class='card'且有style找到 {len(cards_by_style)} 个元素")
            
            # 如果还是找不到，尝试查找所有div看看结构
            all_divs = soup.find_all('div')
            logger.info(f"页面中总共有 {len(all_divs)} 个div元素")
            if len(all_divs) > 0 and len(all_divs) < 50:
                logger.info("前10个div的class属性:")
                for i, div in enumerate(all_divs[:10], 1):
                    div_class = div.get('class', [])
                    logger.info(f"  div {i}: class={div_class}")
            
            return soup
        except requests.RequestException as e:
            logger.error(f"请求失败: {e}")
            return None
    
    def extract_accounts(self, soup: BeautifulSoup) -> List[Dict]:
        """从页面 HTML 解析列表条目（邮箱、地区、状态等）"""
        accounts = []
        
        # 方法1: 通过HTML结构提取（更可靠）
        accounts = self._extract_by_structure(soup)
        
        # 方法2: 如果方法1失败，使用正则表达式
        if not accounts:
            content = soup.get_text()
            pattern = r'#####\s*([^\n【]+)【([^】]+)】.*?账号状态[：:]\s*([^\n]+).*?检测时间[：:]\s*([^\n]+).*?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
            matches = re.finditer(pattern, content, re.DOTALL)
            
            for match in matches:
                account_name = match.group(1).strip()
                region = match.group(2).strip()
                status = match.group(3).strip()
                check_time = match.group(4).strip()
                email = match.group(5).strip()
                
                password = self._extract_password(soup, account_name, email)
                
                account_info = {
                    'account': account_name,
                    'email': email,
                    'password': password,
                    'region': self._map_region(region),
                    'status': self._map_status(status),
                    'check_time': check_time,
                    'crawl_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                accounts.append(account_info)
        
        return accounts
    
    def _map_region(self, region: str) -> str:
        """映射地区代码"""
        region_map = {
            '美国': 'US',
            '美区': 'US',
            '美区ID': 'US',
            '美区小火箭ID': 'US',
            '中国': 'CN',
            '中国大陆': 'CN',
            '香港': 'HK',
            '台湾': 'TW',
            '日本': 'JP',
            '韩国': 'KR',
            '新加坡': 'SG',
            '英国': 'GB',
            '俄罗斯': 'RU',
            '越南': 'VN',
            '马来西亚': 'MY'
        }
        return region_map.get(region, 'US')
    
    def _map_status(self, status: str) -> str:
        """映射状态"""
        if '正常' in status:
            return '正常'
        elif '被锁' in status or '锁定' in status:
            return '被锁'
        else:
            return '其它'
    
    def _extract_password(self, soup: BeautifulSoup, account_name: str, email: str) -> str:
        """尝试从 DOM/脚本中解析登录辅助字段"""
        password = ""
        
        # 方法1: 查找包含邮箱的元素，然后查找密码相关的data属性
        email_elements = soup.find_all(string=re.compile(re.escape(email)))
        
        for elem in email_elements:
            parent = elem.find_parent()
            if parent:
                current = parent
                for _ in range(5):
                    if current:
                        password_attr = (current.get('data-password') or 
                                        current.get('data-pwd') or 
                                        current.get('data-pass'))
                        if password_attr:
                            password = password_attr
                            break
                        
                        copy_btn = current.find(string=re.compile('复制密码'))
                        if copy_btn:
                            btn_parent = copy_btn.find_parent()
                            if btn_parent:
                                password_attr = (btn_parent.get('data-password') or 
                                                btn_parent.get('data-pwd') or
                                                btn_parent.get('data-pass'))
                                if password_attr:
                                    password = password_attr
                                    break
                                
                                onclick = btn_parent.get('onclick', '')
                                pwd_match = re.search(r'["\']([^"\']{6,})["\']', onclick)
                                if pwd_match:
                                    password = pwd_match.group(1)
                                    break
                        
                        current = current.find_parent()
                    
                    if password:
                        break
                
                if password:
                    break
        
        # 方法2: 从JavaScript代码中提取密码
        if not password:
            scripts = soup.find_all('script')
            for script in scripts:
                script_text = script.string or ""
                if email in script_text:
                    pwd_patterns = [
                        r'["\']([^"\']{6,})["\']',
                        r'password["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                        r'pwd["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                    ]
                    for pattern in pwd_patterns:
                        matches = re.findall(pattern, script_text)
                        if matches:
                            password = matches[-1]
                            break
        
        return password
    
    def _decode_cf_email(self, cf_email_element) -> str:
        """解码页面中经混淆/编码的邮箱展示（常见于 CDN 邮箱保护）"""
        try:
            # 尝试从data-cfemail属性获取
            cf_email = cf_email_element.get('data-cfemail', '')
            if not cf_email:
                # 尝试从href中提取
                href = cf_email_element.get('href', '')
                if 'email-protection#' in href:
                    cf_email = href.split('email-protection#')[-1]
            
            if cf_email:
                # 常见 hex-xor 邮箱解码
                # 将十六进制字符串转换为字节
                r = int(cf_email[:2], 16)
                email = ''.join([chr(int(cf_email[i:i+2], 16) ^ r) for i in range(2, len(cf_email), 2)])
                return email
        except:
            pass
        
        # 如果解码失败，返回空字符串
        return ""
    
    def _extract_by_structure(self, soup: BeautifulSoup) -> List[Dict]:
        """通过HTML结构提取账号信息 - 基于实际HTML结构"""
        accounts = []
        
        # 运行逻辑说明：
        # 1. 先找外层容器：<div class="card"> - 这是每个账号的容器
        # 2. 从card里找：<div class="card-header"> 包含 <h5> 包含 <span>账号信息</span>
        # 3. 从 card 里找：<div class="card-body"> 含复制类按钮等
        
        # 尝试多种方式查找card元素（外层容器）
        # 方法1: 查找class包含'card'且有style属性的div（支持多个class，如"card border border-success"）
        cards = soup.find_all('div', class_=lambda x: x and 'card' in x, attrs={'style': True})
        logger.info(f"方法1: 找到 {len(cards)} 个card元素（class包含'card'且有style）")
        
        # 方法2: 如果方法1失败，尝试查找class包含'card'的div（支持多个class）
        if not cards:
            cards = soup.find_all('div', class_=lambda x: x and 'card' in x)
            logger.info(f"方法2: 找到 {len(cards)} 个card元素（class包含'card'）")
        
        # 方法3: 如果还是失败，尝试查找class='card'（精确匹配）
        if not cards:
            cards = soup.find_all('div', class_='card')
            logger.info(f"方法3: 找到 {len(cards)} 个card元素（class='card'精确匹配）")
        
        # 方法4: 如果还是失败，尝试查找包含'card'的class（正则）
        if not cards:
            cards = soup.find_all('div', class_=re.compile('card', re.I))
            logger.info(f"方法4: 找到 {len(cards)} 个card元素（class包含'card'正则）")
        
        # 方法5: 查找所有包含账号信息的div（通过card-body或card-header）
        if not cards:
            # 查找包含邮箱或@符号的div，并且有card-body或card-header
            all_divs = soup.find_all('div')
            for div in all_divs:
                # 检查是否有card-body或card-header子元素
                has_card_body = div.find('div', class_=lambda x: x and 'card-body' in x) is not None
                has_card_header = div.find('div', class_=lambda x: x and 'card-header' in x) is not None
                if has_card_body or has_card_header:
                    cards.append(div)
            logger.info(f"方法5: 找到 {len(cards)} 个可能包含账号的div元素（通过card-body/card-header）")
        
        # 方法6: 如果还是找不到card，直接查找包含账号信息的span元素（备用方案）
        if not cards:
            logger.info("方法6: 尝试直接查找包含账号信息的span元素...")
            # 查找所有包含邮箱格式的span（支持***格式和完整邮箱）
            account_spans = []
            # 查找所有span元素
            all_spans = soup.find_all('span')
            logger.info(f"页面中总共有 {len(all_spans)} 个span元素")
            
            for span in all_spans:
                span_text = span.get_text().strip()
                # 检查是否包含邮箱格式
                if re.search(r'[a-zA-Z0-9._%+-]+(\*\*\*)?@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', span_text):
                    account_spans.append(span)
                    logger.info(f"找到账号span: {span_text[:50]}")
            
            logger.info(f"找到 {len(account_spans)} 个包含账号的span元素")
            
            # 从span向上查找包含它的card容器
            for span in account_spans:
                # 向上查找，找到包含card-header或card-body的div
                parent = span.find_parent()
                depth = 0
                while parent and depth < 10:  # 最多向上查找10层
                    if parent.name == 'div':
                        parent_class = parent.get('class', [])
                        class_str = ' '.join(parent_class) if parent_class else ''
                        # 检查是否包含card相关的class
                        if ('card' in class_str.lower() or 
                            'card-header' in class_str.lower() or 
                            'card-body' in class_str.lower()):
                            if parent not in cards:
                                cards.append(parent)
                                logger.info(f"通过span找到容器: class={class_str}")
                                break
                    parent = parent.find_parent()
                    depth += 1
            
            logger.info(f"方法6: 通过span找到 {len(cards)} 个可能包含账号的容器")
        
        for card in cards:
            try:
                # 运行逻辑：
                # HTML结构：<div class="card"> 
                #   -> <div class="card-header"> 
                #       -> <h5 class="my-0"> 
                #           -> <span style="color: #6FD088">账号</span><span>【地区】</span>
                #   -> <div class="card-body"> 
                #       -> 复制类按钮等
                
                # 提取h5标签中的账号名和地区
                h5 = card.find('h5', class_='my-0')
                if not h5:
                    # 如果找不到h5，尝试直接从card-header或card-body中查找span
                    card_header = card.find('div', class_=lambda x: x and 'card-header' in x)
                    if card_header:
                        # 从card-header中查找包含账号的span
                        account_spans = card_header.find_all('span', string=re.compile(r'[a-zA-Z0-9._%+-]+(\*\*\*)?@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'))
                        if account_spans:
                            # 找到了账号span，继续处理
                            h5 = card_header  # 用card-header代替h5
                        else:
                            continue
                    else:
                        continue
                
                # 从h5中提取账号名和地区
                h5_text = h5.get_text()
                account_name = ""
                region = ""
                
                # 提取账号名和地区（从span中）
                spans = h5.find_all('span')
                for span in spans:
                    text = span.get_text().strip()
                    # 提取账号名
                    if '@' in text or '***' in text:
                        account_name = text
                    # 提取地区（从span中查找【地区】格式）- 支持多种编码
                    # 注意：排除站点品牌名（勿当地区）
                    if not region:
                        # 方法1: 标准【】格式
                        region_match = re.search(r'【([^】]+)】', text)
                        if region_match:
                            potential_region = region_match.group(1).strip()
                            if potential_region and not self._is_brand_region_text(potential_region):
                                region = potential_region
                        else:
                            # 方法2: 可能是编码问题，尝试查找包含地区关键词的文本
                            region_keywords = ['香港', '美国', '中国', '台湾', '日本', '韩国', '新加坡', '英国', '俄罗斯', '越南', '马来西亚', '美区']
                            for keyword in region_keywords:
                                if keyword in text and 'CC宝盒' not in text and 'TK宝盒' not in text:
                                    region = keyword
                                    break
                
                # 如果从span中没找到地区，再从整个h5文本中查找（排除品牌文案）
                if not region:
                    # 方法1: 标准【】格式
                    region_match = re.search(r'【([^】]+)】', h5_text)
                    if region_match:
                        potential_region = region_match.group(1).strip()
                        if potential_region and not self._is_brand_region_text(potential_region):
                            region = potential_region
                    else:
                        # 方法2: 查找地区关键词
                        region_keywords = ['香港', '美国', '中国', '台湾', '日本', '韩国', '新加坡', '英国', '俄罗斯', '越南', '马来西亚', '美区']
                        for keyword in region_keywords:
                            if keyword in h5_text and 'CC宝盒' not in h5_text and 'TK宝盒' not in h5_text:
                                region = keyword
                                break
                
                # 如果没找到账号名，从h5文本中提取
                if not account_name:
                    account_match = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', h5_text)
                    if not account_match:
                        account_match = re.search(r'([a-zA-Z0-9]+\*\*\*@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', h5_text)
                    if account_match:
                        account_name = account_match.group(1)
                
                # 如果账号名包含***，尝试从card-body中获取完整邮箱
                card_body = card.find('div', class_='card-body')
                if not card_body:
                    continue
                
                # 提取邮箱（页面内编码字段）
                email = ""
                cf_email_elem = card_body.find('a', class_='__cf_email__')
                if cf_email_elem:
                    email = self._decode_cf_email(cf_email_elem)
                
                # 如果解码失败，尝试从data-cfemail属性解码
                if not email:
                    cf_email_span = card_body.find('span', class_='__cf_email__')
                    if cf_email_span:
                        email = self._decode_cf_email(cf_email_span)
                
                # 从按钮 onclick 解析登录辅助字段
                password = ""
                password_buttons = card_body.find_all('button')
                
                for btn in password_buttons:
                    btn_text = btn.get_text().strip()
                    onclick = btn.get('onclick', '')
                    
                    # 检查是否为「复制口令/复制」类按钮（页面文案勿改）
                    is_password_btn = (
                        '密码' in btn_text or 
                        'copy(' in onclick.lower() or
                        ('复制' in btn_text and len(onclick) > 10)
                    )
                    
                    if is_password_btn and onclick:
                        # 尝试多种模式匹配密码（按优先级）
                        patterns = [
                            (r"copy\(['\"]([^'\"]+)['\"]\)", "copy('密码')"),
                            (r"copy\(['\"]?([A-Za-z0-9]{4,20})['\"]?\)", "copy(密码)宽松"),
                            (r"copy\(['\"]([^'\"]+)['\"]", "copy('密码（不完整）"),
                            (r"copy\(([^\)]+)\)", "copy(密码)"),
                            (r"['\"]([A-Za-z0-9]{6,})['\"]", "引号中的字母数字"),
                            (r"['\"]([^'\"]{4,20})['\"]", "引号中4-20字符"),
                        ]
                        
                        for pattern, desc in patterns:
                            pwd_match = re.search(pattern, onclick)
                            if pwd_match:
                                potential_pwd = pwd_match.group(1).strip()
                                # 更严格的过滤
                                if (len(potential_pwd) >= 4 and 
                                    len(potential_pwd) <= 30 and
                                    not potential_pwd.startswith('http') and
                                    not potential_pwd.startswith('window') and
                                    not potential_pwd.startswith('return') and
                                    not potential_pwd.startswith('if') and
                                    not 'function' in potential_pwd.lower() and
                                    not potential_pwd.startswith('__') and
                                    re.match(r'^[A-Za-z0-9_\-]+$', potential_pwd)):  # 只包含字母数字下划线横线
                                    password = potential_pwd
                                    break
                        
                        if password:
                            break
                
                # 如果还没找到，尝试从所有按钮中查找（不限制按钮文本）
                if not password:
                    for btn in password_buttons:
                        onclick = btn.get('onclick', '')
                        if 'copy(' in onclick.lower() and len(onclick) > 20:
                            # 尝试提取
                            pwd_match = re.search(r"copy\(['\"]?([A-Za-z0-9]{4,20})['\"]?\)", onclick)
                            if pwd_match:
                                potential_pwd = pwd_match.group(1).strip()
                                if (re.match(r'^[A-Za-z0-9_\-]+$', potential_pwd) and
                                    not potential_pwd.startswith('http')):
                                    password = potential_pwd
                                    break
                
                # 提取状态
                status = "正常"
                status_elem = card_body.find('p', class_='card-title')
                if status_elem:
                    status_text = status_elem.get_text()
                    if '账号状态' in status_text:
                        status_match = re.search(r'账号状态[：:]\s*([^\n]+)', status_text)
                        if status_match:
                            status = status_match.group(1).strip()
                
                # 提取检测时间
                check_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                # 查找所有card-text元素
                time_elems = card_body.find_all('p', class_='card-text')
                for time_elem in time_elems:
                    time_text = time_elem.get_text().strip()
                    # 检查是否包含时间信息
                    if '检测时间' in time_text or '更新' in time_text or re.search(r'\d{4}-\d{2}-\d{2}', time_text):
                        # 尝试多种时间格式
                        time_patterns = [
                            r'检测时间[：:]\s*([^\n]+)',  # 检测时间：2025-11-07 01:34:08
                            r'检测时间[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})',  # 完整时间格式
                            r'([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})',  # 直接匹配时间格式
                            r'(\d+分钟前更新)',  # 30分钟前更新
                            r'(\d+小时前更新)',  # 1小时前更新
                        ]
                        for pattern in time_patterns:
                            time_match = re.search(pattern, time_text)
                            if time_match:
                                check_time = time_match.group(1).strip()
                                break
                        if check_time != datetime.now().strftime('%Y-%m-%d %H:%M:%S'):
                            break
                
                # 如果地区为空，尝试从card-body中查找（但要排除状态区域）
                if not region:
                    # 只从card-body的文本中查找，但要排除状态区域（card-title）
                    # 先排除状态区域
                    status_elem = card_body.find('p', class_='card-title')
                    card_body_text = card_body.get_text()
                    if status_elem:
                        # 从card_body_text中移除状态区域的文本
                        status_text = status_elem.get_text()
                        card_body_text = card_body_text.replace(status_text, '')
                    
                    region_match = re.search(r'【([^】]+)】', card_body_text)
                    if region_match:
                        potential_region = region_match.group(1).strip()
                        if potential_region and not self._is_brand_region_text(potential_region):
                            region = potential_region
                
                # 仅保留邮箱与登录辅助字段均解析成功的记录
                if email or account_name:
                    # 如果没有邮箱，使用账号名
                    if not email:
                        email = account_name
                    
                    # 登录辅助字段为空则跳过
                    if not password or password.strip() == "":
                        logger.info(f"跳过条目（登录辅助字段未解析）: {email} ({region or '未知'})")
                        continue
                    
                    # 写入一条完整记录
                    accounts.append({
                        'account': account_name,
                        'email': email,
                        'fullEmail': email,
                        'password': password,
                        'region': self._map_region(region) if region else 'US',
                        'regionName': region if region else '美国',
                        'status': self._map_status(status),
                        'checkTime': check_time if check_time else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'crawl_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                    logger.info(f"✅ 解析条目: {email} ({region or '未知'}) 字段预览: {password[:10]}...")
            
            except Exception as e:
                logger.warning(f"解析条目时出错: {e}")
                continue
        
        return accounts
    
    def _extract_password_from_container(self, container, email: str) -> str:
        """从容器按钮 onclick 中解析登录辅助字段"""
        password = ""
        
        # 查找所有包含"复制密码"的按钮
        buttons = container.find_all('button')
        for btn in buttons:
            btn_text = btn.get_text()
            if '复制密码' in btn_text:
                onclick = btn.get('onclick', '')
                if onclick and 'copy(' in onclick:
                    # 提取copy('密码')中的密码
                    pwd_match = re.search(r"copy\(['\"]([^'\"]+)['\"]\)", onclick)
                    if pwd_match:
                        password = pwd_match.group(1)
                        break
        
        return password
    
    def run_fetch(self) -> List[Dict]:
        """按 source_urls 逐页拉取 HTML 并解析，按邮箱合并去重（保留先出现的条目）"""
        logger.info("开始拉取远程列表数据...")
        logger.info(f"来源页面数: {len(self.source_urls)} -> {self.source_urls}")
        
        merged: List[Dict] = []
        seen_email: set = set()
        
        for page_url in self.source_urls:
            logger.info("-" * 40)
            logger.info(f"数据来源: {page_url}")
            soup = self.fetch_page(page_url)
            if not soup:
                logger.warning(f"无法获取页面，跳过: {page_url}")
                continue
            
            page_accounts = self.extract_accounts(soup)
            new_count = 0
            for acc in page_accounts:
                email_key = (acc.get("fullEmail") or acc.get("email") or "").strip().lower()
                if email_key:
                    if email_key in seen_email:
                        continue
                    seen_email.add(email_key)
                acc["source_page"] = page_url
                merged.append(acc)
                new_count += 1
            
            logger.info(f"本页提取 {len(page_accounts)} 条，合并后新增 {new_count} 条（去重后累计 {len(merged)}）")
        
        self.accounts = merged
        logger.info(f"全部来源合并完成，共 {len(merged)} 条")
        return merged
    
    def _load_vpn_ads(self) -> List[Dict]:
        """加载VPN广告数据（从文件或使用默认值）"""
        import os
        # 尝试从文件读取
        vpn_file = 'vpn_ads.json'
        if os.path.exists(vpn_file):
            try:
                with open(vpn_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and 'vpn_ads' in data:
                        return data['vpn_ads']
            except:
                pass
        
        # 如果没有文件，返回空数组（保持原样，不修改）
        return []
    
    def format_for_api(self, max_accounts: int = None) -> Dict:
        """
        格式化数据为API格式（符合网站要求）
        
        Args:
            max_accounts: 每个分组最大账号数（None表示使用所有账号）
        """
        import time
        
        # 转换为现有系统的格式
        formatted_accounts = []
        accounts_to_format = self.accounts[:max_accounts] if max_accounts else self.accounts
        
        for i, acc in enumerate(accounts_to_format, 1):
            # 获取地区信息
            region_text = acc.get('regionName', '').strip() or acc.get('region', '').strip()
            # 如果region为空，默认使用"美国"
            if not region_text:
                region_text = '美国'
            
            # 映射地区代码
            region_name_map = {
                '美国': 'US', '中国': 'CN', '香港': 'HK', '台湾': 'TW',
                '日本': 'JP', '韩国': 'KR', '新加坡': 'SG', '英国': 'GB',
                '俄罗斯': 'RU', '越南': 'VN', '马来西亚': 'MY'
            }
            region_code = region_name_map.get(region_text, 'US')
            region_name = region_text  # 使用region_text（如果为空则已经是"美国"）
            
            formatted_accounts.append({
                'id': f'1-{i}',
                'fullEmail': acc.get('fullEmail') or acc.get('email', ''),
                'password': acc.get('password', ''),
                'status': acc.get('status', '正常'),
                'checkTime': acc.get('checkTime') or acc.get('crawl_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                'region': region_code,
                'regionName': region_name
            })
        
        # 加载VPN广告数据（保持原样，不修改）
        vpn_ads = self._load_vpn_ads()
        
        # 生成Unix时间戳
        timestamp = int(time.time())
        
        # 返回符合网站要求的格式
        return {
            'timestamp': timestamp,
            'data': {
                'accounts': {
                    'group1': formatted_accounts,
                    'group2': []  # group2保持为空
                },
                'vpn_ads': vpn_ads  # VPN广告部分保持原样，不修改
            }
        }
    
    def sync_to_api(self) -> bool:
        """
        同步数据到网站后台API
        
        Returns:
            是否同步成功
        """
        if not self.api_url:
            logger.warning("未配置API URL，跳过同步")
            return False
        
        try:
            formatted_data = self.format_for_api()
            
            logger.info(f"正在同步 {len(formatted_data['data']['accounts']['group1'])} 条到 API...")
            
            response = self.session.post(
                f"{self.api_url}?type=accounts",
                json=formatted_data,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            response.raise_for_status()
            result = response.json()
            
            if result.get('success'):
                logger.info(f"✅ 数据同步成功！时间戳: {result.get('timestamp')}")
                return True
            else:
                logger.error(f"❌ 同步失败: {result.get('error', '未知错误')}")
                return False
                
        except requests.RequestException as e:
            logger.error(f"❌ API同步失败: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ 同步过程出错: {e}")
            return False
    
    def save_to_json(self, filename: str = 'apple_ids.json'):
        """保存到JSON文件"""
        data = {
            'total': len(self.accounts),
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'source_url': self.base_url,
            'source_urls': self.source_urls,
            'accounts': self.accounts
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"已保存 {len(self.accounts)} 个账号到 {filename}")
    
    def save_to_simple_json(self, filename: str = 'apple_ids_simple.json'):
        """保存简化版 JSON（邮箱 + 地区代码 + 登录辅助字段）"""
        simple_data = []
        for acc in self.accounts:
            simple_data.append({
                'email': acc.get('fullEmail') or acc.get('email', ''),
                'password': acc.get('password', ''),
                'region': acc.get('region', 'US')
            })
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(simple_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"已保存简化数据到 {filename}")


def main():
    """主函数"""
    import sys
    import os
    
    # 从命令行参数或环境变量获取API URL
    api_url = None
    if len(sys.argv) > 1:
        api_url = sys.argv[1]
    else:
        # 可以从配置文件读取
        api_url = os.environ.get('API_URL')
    
    client = RemoteFeedClient(api_url=api_url)
    accounts = client.run_fetch()
    
    if accounts:
        # 保存本地文件
        client.save_to_json('apple_ids.json')
        client.save_to_simple_json('apple_ids_simple.json')
        
        # 同步到API（如果配置了）
        if api_url:
            client.sync_to_api()
        
        print(f"\n拉取完成！共解析 {len(accounts)} 条")
        print("\n前5个账号示例:")
        for i, acc in enumerate(accounts[:5], 1):
            email = acc.get('fullEmail') or acc.get('email', '')
            print(f"{i}. {email} | {acc.get('region', 'US')} | {acc.get('status', '正常')}")
    else:
        print("未解析到有效条目，请检查页面结构或网络")


# 兼容旧代码：类名与方法名
AppleIDCrawler = RemoteFeedClient
RemoteFeedClient.crawl = RemoteFeedClient.run_fetch


if __name__ == '__main__':
    main()
