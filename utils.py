import re
from database import get_whitelist_domains

def contains_non_whitelisted_link(text: str) -> bool:
    """Проверяет, содержит ли текст ссылку, домен которой не в белом списке"""
    if not text:
        return False
    urls = re.findall(r'https?://(?:[-\w]+\.)+[a-z]{2,}(?:/[^\s]*)?', text, re.I)
    if not urls:
        return False
    whitelist = get_whitelist_domains()
    for url in urls:
        domain_match = re.search(r'https?://([^/]+)', url)
        if domain_match:
            domain = domain_match.group(1).lower()
            allowed = any(domain == d or domain.endswith('.' + d) for d in whitelist)
            if not allowed:
                return True
    return False