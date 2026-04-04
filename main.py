"""
主执行脚本 - 从远程公开页拉取列表并同步到网站后台与 GitHub
"""

from apple_id_crawler import RemoteFeedClient
from github_sync import GitHubSync
import os
import logging
import time
import json
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("远程列表同步任务启动")
    logger.info("=" * 60)
    
    # 配置API URL（从环境变量或配置文件读取）
    api_url = os.environ.get('API_URL') or os.environ.get('WEBSITE_API_URL')
    # 例如: "http://your-domain.com/data_sync.php"
    
    # 步骤1: 拉取远程数据
    logger.info("\n[步骤1] 开始拉取远程列表...")
    fetcher = RemoteFeedClient(api_url=api_url)
    accounts = fetcher.run_fetch()
    
    if not accounts:
        logger.error("未拉取到有效数据，终止执行")
        # 即使没有账号，也创建空文件，避免Git错误
        import json
        with open('apple_ids.json', 'w', encoding='utf-8') as f:
            json.dump({'accounts': [], 'total': 0, 'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, f, ensure_ascii=False, indent=2)
        logger.info("已创建空的apple_ids.json文件")
        # 继续执行，生成其他文件
        accounts = []
    
    # 保存本地数据（即使accounts为空也会创建文件）
    if accounts:
        fetcher.save_to_json('apple_ids.json')
        fetcher.save_to_simple_json('apple_ids_simple.json')
    else:
        # 如果没有账号，创建空文件
        with open('apple_ids.json', 'w', encoding='utf-8') as f:
            json.dump({'accounts': [], 'total': 0, 'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, f, ensure_ascii=False, indent=2)
        with open('apple_ids_simple.json', 'w', encoding='utf-8') as f:
            json.dump({'accounts': [], 'total': 0}, f, ensure_ascii=False, indent=2)
        logger.info("已创建空的apple_ids.json和apple_ids_simple.json文件")
    
    logger.info(f"成功拉取并解析 {len(accounts)} 条")
    
    # 步骤2: 同步到网站后台API
    if api_url:
        logger.info("\n[步骤2] 开始同步到网站后台...")
        if fetcher.sync_to_api():
            logger.info("✅ 网站后台同步成功！")
        else:
            logger.warning("⚠️ 网站后台同步失败，请检查API配置")
    else:
        logger.warning("⚠️ 未配置API URL，跳过网站后台同步")
        logger.info("提示: 设置环境变量 API_URL 或 WEBSITE_API_URL 来启用自动同步")
    
    # 步骤3: 生成GitHub文件（供博客使用）
    # 注意：在GitHub Actions中，文件提交由workflow处理
    logger.info("\n[步骤3] 生成GitHub文件...")
    
    if os.environ.get('GITHUB_ACTIONS'):
        # 在 GitHub Actions 中，直接用内存中的列表生成文件
        if accounts:
            logger.info(f"使用已解析的 {len(accounts)} 条生成文件...")
            sync = GitHubSync()
            # 直接使用accounts列表生成文件，不需要从文件加载
            sync.create_api_file(accounts, 'api_data.json')
            logger.info("✅ 已生成 api_data.json")
            sync.create_blog_file(accounts, 'blog_accounts.json')
            logger.info("✅ 已生成 blog_accounts.json")
            sync.create_simple_file(accounts, 'accounts_simple.json')
            logger.info("✅ 已生成 accounts_simple.json")
            logger.info("✅ 所有文件已生成，将由GitHub Actions自动提交")
        else:
            logger.warning("⚠️ 没有账号数据，生成空文件")
            sync = GitHubSync()
            # 即使没有账号，也生成所有文件（空文件）
            sync.create_api_file([], 'api_data.json')
            logger.info("✅ 已生成 api_data.json")
            sync.create_blog_file([], 'blog_accounts.json')
            logger.info("✅ 已生成 blog_accounts.json")
            sync.create_simple_file([], 'accounts_simple.json')
            logger.info("✅ 已生成 accounts_simple.json")
            logger.info("✅ 所有文件已生成（空文件），将由GitHub Actions自动提交")
    else:
        # 本地运行，执行完整的同步
        sync = GitHubSync()
        sync.sync()
    
    logger.info("\n" + "=" * 60)
    logger.info("所有任务完成！")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
