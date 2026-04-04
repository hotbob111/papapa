"""
GitHub 同步脚本
将本地解析得到的列表数据写入 JSON 并可选提交到仓库，供站点与博客读取。
"""

import json
import random
import subprocess
import sys
import os
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GitHubSync:
    """GitHub同步类"""
    
    def __init__(self, repo_path: str = ".", github_repo: str = None):
        """
        初始化
        
        Args:
            repo_path: 本地仓库路径
            github_repo: GitHub仓库地址（格式：username/repo）
        """
        self.repo_path = repo_path
        self.github_repo = github_repo
    
    def load_accounts(self, filename: str = 'apple_ids.json') -> list:
        """加载账号数据"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('accounts', [])
        except FileNotFoundError:
            logger.error(f"文件不存在: {filename}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析错误: {e}")
            return []
    
    def create_api_file(self, accounts: list, filename: str = 'api_data.json'):
        """创建API数据文件（供网站后台使用，符合网站格式要求）"""
        import time
        
        # 加载VPN广告数据
        vpn_ads = []
        vpn_file = 'vpn_ads.json'
        try:
            if os.path.exists(vpn_file):
                with open(vpn_file, 'r', encoding='utf-8') as f:
                    vpn_data = json.load(f)
                    if isinstance(vpn_data, list):
                        vpn_ads = vpn_data
                    elif isinstance(vpn_data, dict) and 'vpn_ads' in vpn_data:
                        vpn_ads = vpn_data['vpn_ads']
        except:
            pass
        
        # 格式化账号数据
        formatted_accounts = []
        region_name_map = {
            'US': '美国', 'CN': '中国', 'HK': '香港', 'TW': '台湾',
            'JP': '日本', 'KR': '韩国', 'SG': '新加坡', 'GB': '英国',
            'RU': '俄罗斯', 'VN': '越南', 'MY': '马来西亚'
        }
        
        for i, acc in enumerate(accounts, 1):
            # 获取地区信息
            region_text = acc.get('regionName', '').strip() or acc.get('region', '').strip()
            # 如果region为空，默认使用"美国"
            if not region_text:
                region_text = '美国'
            
            # 映射地区代码（反向映射：地区名称 -> 代码）
            region_code_map = {
                '美国': 'US', '中国': 'CN', '香港': 'HK', '台湾': 'TW',
                '日本': 'JP', '韩国': 'KR', '新加坡': 'SG', '英国': 'GB',
                '俄罗斯': 'RU', '越南': 'VN', '马来西亚': 'MY'
            }
            region_code = region_code_map.get(region_text, 'US')
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
        
        # 生成符合网站要求的格式
        api_data = {
            'timestamp': int(time.time()),
            'data': {
                'accounts': {
                    'group1': formatted_accounts,
                    'group2': []
                },
                'vpn_ads': vpn_ads
            }
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(api_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"已创建API数据文件: {filename} (包含 {len(formatted_accounts)} 个账号)")
    
    def create_blog_file(self, accounts: list, filename: str = 'blog_accounts.json'):
        """创建博客数据文件（随机选择2个账号）"""
        if len(accounts) < 2:
            logger.warning("账号数量不足2个，无法创建博客文件")
            return
        
        # 随机选择2个账号
        selected_accounts = random.sample(accounts, min(2, len(accounts)))
        
        blog_data = {
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'count': len(selected_accounts),
            'accounts': selected_accounts
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(blog_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"已创建博客数据文件: {filename} (包含 {len(selected_accounts)} 个账号)")
    
    def create_simple_file(self, accounts: list, filename: str = 'accounts_simple.json'):
        """创建简化版数据文件（邮箱、地区与登录辅助字段）"""
        simple_data = []
        for acc in accounts:
            simple_data.append({
                'email': acc.get('email', ''),
                'password': acc.get('password', ''),
                'region': acc.get('region', '')
            })
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(simple_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"已创建简化数据文件: {filename}")
    
    def git_add_and_commit(self, files: list, message: str = None):
        """Git添加和提交"""
        if not message:
            message = f"自动更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        try:
            # 添加文件
            for file in files:
                if os.path.exists(file):
                    subprocess.run(
                        ['git', 'add', file],
                        cwd=self.repo_path,
                        check=True,
                        capture_output=True
                    )
                    logger.info(f"已添加文件: {file}")
            
            # 提交
            subprocess.run(
                ['git', 'commit', '-m', message],
                cwd=self.repo_path,
                check=True,
                capture_output=True
            )
            logger.info(f"已提交: {message}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Git操作失败: {e}")
            return False
    
    def git_push(self):
        """推送到GitHub"""
        try:
            result = subprocess.run(
                ['git', 'push'],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                logger.info("已推送到GitHub")
                return True
            else:
                logger.error(f"推送失败: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"推送错误: {e}")
            return False
    
    def sync(self):
        """执行同步"""
        logger.info("开始同步到GitHub...")
        
        # 加载账号数据
        accounts = self.load_accounts('apple_ids.json')
        if not accounts:
            logger.error("没有账号数据可同步")
            return False
        
        logger.info(f"加载了 {len(accounts)} 个账号")
        
        # 创建各种格式的数据文件
        self.create_api_file(accounts, 'api_data.json')
        self.create_blog_file(accounts, 'blog_accounts.json')
        self.create_simple_file(accounts, 'accounts_simple.json')
        
        # 检查是否在Git仓库中
        if not os.path.exists(os.path.join(self.repo_path, '.git')):
            logger.warning("当前目录不是Git仓库，跳过Git操作")
            logger.info("请先初始化Git仓库: git init")
            logger.info("然后添加远程仓库: git remote add origin <your-repo-url>")
            return True
        
        # Git操作
        files_to_commit = [
            'apple_ids.json',
            'api_data.json',
            'blog_accounts.json',
            'accounts_simple.json'
        ]
        
        if self.git_add_and_commit(files_to_commit):
            self.git_push()
        
        logger.info("同步完成")
        return True


def main():
    """主函数"""
    # 配置GitHub仓库（如果需要）
    # GITHUB_REPO = "your-username/your-repo"  # 例如: "username/apple-ids"
    
    sync = GitHubSync()
    sync.sync()


if __name__ == '__main__':
    main()


