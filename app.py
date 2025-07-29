import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import time
import re
from collections import deque
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
from PIL import Image
import base64
import json
from datetime import datetime
import xml.etree.ElementTree as ET
from urllib.robotparser import RobotFileParser

# Page config
st.set_page_config(page_title="Ultra Frog SEO Crawler", layout="wide", page_icon="🐸")

# Initialize session state
if 'crawl_data' not in st.session_state:
    st.session_state.crawl_data = []
if 'crawling' not in st.session_state:
    st.session_state.crawling = False
if 'stop_crawling' not in st.session_state:
    st.session_state.stop_crawling = False
if 'visited_urls' not in st.session_state:
    st.session_state.visited_urls = set()

class UltraFrogCrawler:
    def __init__(self, max_urls=100000, ignore_robots=False):
        self.max_urls = max_urls
        self.ignore_robots = ignore_robots
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Ultra Frog SEO Crawler/1.0 (https://ultrafrog.seo)'
        })
        self.robots_cache = {}
    
    def can_fetch(self, url):
        if self.ignore_robots:
            return True
        
        try:
            domain = urlparse(url).netloc
            if domain not in self.robots_cache:
                try:
                    rp = RobotFileParser()
                    rp.set_url(f"http://{domain}/robots.txt")
                    rp.read()
                    self.robots_cache[domain] = rp
                except:
                    self.robots_cache[domain] = None
            
            if self.robots_cache[domain] is None:
                return True
            
            return self.robots_cache[domain].can_fetch('*', url)
        except:
            return True
    
    def extract_sitemap_urls(self, sitemap_url):
        """Extract URLs from XML sitemap"""
        urls = []
        try:
            response = self.session.get(sitemap_url, timeout=10)
            if response.status_code == 200:
                # Parse XML
                root = ET.fromstring(response.content)
                
                # Handle different sitemap formats
                namespaces = {
                    'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9',
                    'image': 'http://www.google.com/schemas/sitemap-image/1.1',
                    'video': 'http://www.google.com/schemas/sitemap-video/1.1'
                }
                
                # Check if it's a sitemap index
                sitemapindex = root.findall('.//sitemap:sitemap', namespaces)
                if sitemapindex:
                    # It's a sitemap index, get individual sitemaps
                    for sitemap in sitemapindex:
                        loc = sitemap.find('sitemap:loc', namespaces)
                        if loc is not None:
                            # Recursively get URLs from each sitemap
                            urls.extend(self.extract_sitemap_urls(loc.text))
                else:
                    # It's a regular sitemap, extract URLs
                    url_elements = root.findall('.//sitemap:url', namespaces)
                    for url_elem in url_elements:
                        loc = url_elem.find('sitemap:loc', namespaces)
                        if loc is not None:
                            urls.append(loc.text)
                            
        except Exception as e:
            st.error(f"Error parsing sitemap {sitemap_url}: {e}")
        
        return urls
        
    def extract_page_data(self, url):
        try:
            response = self.session.get(url, timeout=15, allow_redirects=True)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Basic SEO data
            title = soup.find('title')
            title_text = title.get_text().strip() if title else ""
            
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            meta_desc_text = meta_desc.get('content', '') if meta_desc else ""
            
            # Canonical URL
            canonical = soup.find('link', attrs={'rel': 'canonical'})
            canonical_url = canonical.get('href') if canonical else ""
            
            # Meta robots
            meta_robots = soup.find('meta', attrs={'name': 'robots'})
            robots_content = meta_robots.get('content', '') if meta_robots else ""
            
            # Open Graph tags
            og_title = soup.find('meta', attrs={'property': 'og:title'})
            og_desc = soup.find('meta', attrs={'property': 'og:description'})
            og_image = soup.find('meta', attrs={'property': 'og:image'})
            
            # Twitter Card tags
            twitter_title = soup.find('meta', attrs={'name': 'twitter:title'})
            twitter_desc = soup.find('meta', attrs={'name': 'twitter:description'})
            twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
            
            # Header tags analysis
            h1_tags = [h1.get_text().strip() for h1 in soup.find_all('h1')]
            h2_tags = [h2.get_text().strip() for h2 in soup.find_all('h2')]
            h3_tags = [h3.get_text().strip() for h3 in soup.find_all('h3')]
            h4_tags = [h4.get_text().strip() for h4 in soup.find_all('h4')]
            
            # Links analysis
            internal_links = []
            external_links = []
            base_domain = urlparse(url).netloc
            
            for link in soup.find_all('a', href=True):
                href = urljoin(url, link['href'])
                link_text = link.get_text().strip()
                if urlparse(href).netloc == base_domain:
                    internal_links.append({'url': href, 'anchor_text': link_text})
                else:
                    external_links.append({'url': href, 'anchor_text': link_text})
            
            # Images analysis
            images = []
            for img in soup.find_all('img'):
                img_src = urljoin(url, img.get('src', ''))
                try:
                    img_response = self.session.head(img_src, timeout=5)
                    img_size = int(img_response.headers.get('content-length', 0))
                except:
                    img_size = 0
                
                images.append({
                    'src': img_src,
                    'alt': img.get('alt', ''),
                    'title': img.get('title', ''),
                    'size_bytes': img_size,
                    'width': img.get('width', ''),
                    'height': img.get('height', '')
                })
            
            # Schema markup
            scripts = soup.find_all('script', type='application/ld+json')
            schema_types = []
            for script in scripts:
                try:
                    schema_data = json.loads(script.string)
                    if isinstance(schema_data, dict) and '@type' in schema_data:
                        schema_types.append(schema_data['@type'])
                    elif isinstance(schema_data, list):
                        for item in schema_data:
                            if isinstance(item, dict) and '@type' in item:
                                schema_types.append(item['@type'])
                except:
                    pass
            
            # Page speed indicators
            css_files = len(soup.find_all('link', attrs={'rel': 'stylesheet'}))
            js_files = len(soup.find_all('script', src=True))
            
            # Word count
            text_content = soup.get_text()
            word_count = len(text_content.split())
            
            # Redirect chain analysis
            redirect_chain = []
            if hasattr(response, 'history'):
                for resp in response.history:
                    redirect_chain.append({
                        'from': resp.url,
                        'to': resp.headers.get('location', ''),
                        'status': resp.status_code
                    })
            
            return {
                'url': response.url,
                'original_url': url,
                'status_code': response.status_code,
                'title': title_text,
                'title_length': len(title_text),
                'meta_description': meta_desc_text,
                'meta_desc_length': len(meta_desc_text),
                'canonical_url': canonical_url,
                'meta_robots': robots_content,
                'h1_tags': h1_tags,
                'h1_count': len(h1_tags),
                'h2_tags': h2_tags,
                'h2_count': len(h2_tags),
                'h3_tags': h3_tags,
                'h3_count': len(h3_tags),
                'h4_tags': h4_tags,
                'h4_count': len(h4_tags),
                'content_length': len(response.content),
                'word_count': word_count,
                'response_time': response.elapsed.total_seconds(),
                'internal_links': internal_links,
                'external_links': external_links,
                'images': images,
                'image_count': len(images),
                'schema_types': schema_types,
                'schema_count': len(schema_types),
                'redirect_chain': redirect_chain,
                'redirect_count': len(redirect_chain),
                'content_type': response.headers.get('content-type', ''),
                'last_modified': response.headers.get('last-modified', ''),
                'server': response.headers.get('server', ''),
                'css_files': css_files,
                'js_files': js_files,
                'og_title': og_title.get('content', '') if og_title else '',
                'og_description': og_desc.get('content', '') if og_desc else '',
                'og_image': og_image.get('content', '') if og_image else '',
                'twitter_title': twitter_title.get('content', '') if twitter_title else '',
                'twitter_description': twitter_desc.get('content', '') if twitter_desc else '',
                'twitter_image': twitter_image.get('content', '') if twitter_image else '',
                'indexability': self.get_indexability_status(response.status_code, robots_content),
                'crawl_timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'url': url,
                'original_url': url,
                'status_code': 0,
                'error': str(e),
                'title': '', 'title_length': 0, 'meta_description': '', 'meta_desc_length': 0,
                'canonical_url': '', 'meta_robots': '', 'h1_tags': [], 'h1_count': 0,
                'h2_tags': [], 'h2_count': 0, 'h3_tags': [], 'h3_count': 0,
                'h4_tags': [], 'h4_count': 0, 'content_length': 0, 'word_count': 0,
                'response_time': 0, 'internal_links': [], 'external_links': [],
                'images': [], 'image_count': 0, 'schema_types': [], 'schema_count': 0,
                'redirect_chain': [], 'redirect_count': 0, 'content_type': '',
                'last_modified': '', 'server': '', 'css_files': 0, 'js_files': 0,
                'og_title': '', 'og_description': '', 'og_image': '',
                'twitter_title': '', 'twitter_description': '', 'twitter_image': '',
                'indexability': 'Error', 'crawl_timestamp': datetime.now().isoformat()
            }
    
    def get_indexability_status(self, status_code, robots_content):
        if status_code != 200:
            return 'Non-Indexable'
        if 'noindex' in robots_content.lower():
            return 'Non-Indexable'
        return 'Indexable'

def crawl_website(start_url, max_urls, progress_bar, status_text, ignore_robots=False):
    crawler = UltraFrogCrawler(max_urls, ignore_robots)
    urls_to_visit = deque([start_url])
    visited_urls = set()
    crawl_data = []
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        while urls_to_visit and len(visited_urls) < max_urls and not st.session_state.stop_crawling:
            current_batch = []
            for _ in range(min(15, len(urls_to_visit))):
                if urls_to_visit and not st.session_state.stop_crawling:
                    url = urls_to_visit.popleft()
                    if crawler.can_fetch(url):
                        current_batch.append(url)
            
            if not current_batch:
                break
                
            futures = [executor.submit(crawler.extract_page_data, url) for url in current_batch]
            
            for future in as_completed(futures):
                if st.session_state.stop_crawling:
                    break
                try:
                    page_data = future.result()
                    if page_data['url'] not in visited_urls:
                        visited_urls.add(page_data['url'])
                        crawl_data.append(page_data)
                        
                        # Add new internal links to queue
                        for link_data in page_data.get('internal_links', []):
                            link_url = link_data['url']
                            if link_url not in visited_urls and link_url not in urls_to_visit:
                                urls_to_visit.append(link_url)
                        
                        progress = min(len(visited_urls) / max_urls, 1.0)
                        progress_bar.progress(progress)
                        status_text.text(f"Crawled: {len(visited_urls)} URLs | Queue: {len(urls_to_visit)}")
                        
                except Exception as e:
                    st.error(f"Error processing URL: {e}")
            
            if st.session_state.stop_crawling:
                break
    
    return crawl_data  # Fixed: Always return crawl_data

def crawl_from_list(url_list, progress_bar, status_text, ignore_robots=False):
    """Crawl URLs from a provided list"""
    crawler = UltraFrogCrawler(len(url_list), ignore_robots)
    crawl_data = []
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        # Filter URLs based on robots.txt if needed
        valid_urls = []
        for url in url_list:
            if not st.session_state.stop_crawling and crawler.can_fetch(url.strip()):
                valid_urls.append(url.strip())
        
        if not valid_urls:
            return crawl_data
        
        futures = [executor.submit(crawler.extract_page_data, url) for url in valid_urls]
        
        completed = 0
        for future in as_completed(futures):
            if st.session_state.stop_crawling:
                break
            try:
                page_data = future.result()
                crawl_data.append(page_data)
                completed += 1
                
                progress = completed / len(valid_urls)
                progress_bar.progress(progress)
                status_text.text(f"Processed: {completed}/{len(valid_urls)} URLs")
                
            except Exception as e:
                st.error(f"Error processing URL: {e}")
    
    return crawl_data

def crawl_from_sitemap(sitemap_url, max_urls, progress_bar, status_text, ignore_robots=False):
    """Crawl URLs from XML sitemap"""
    crawler = UltraFrogCrawler(max_urls, ignore_robots)
    
    # Extract URLs from sitemap
    status_text.text("🗺️ Extracting URLs from sitemap...")
    sitemap_urls = crawler.extract_sitemap_urls(sitemap_url)
    
    if not sitemap_urls:
        st.error("No URLs found in sitemap or sitemap could not be parsed")
        return []
    
    # Limit URLs if needed
    if len(sitemap_urls) > max_urls:
        sitemap_urls = sitemap_urls[:max_urls]
    
    st.info(f"Found {len(sitemap_urls)} URLs in sitemap")
    
    # Crawl the URLs
    return crawl_from_list(sitemap_urls, progress_bar, status_text, ignore_robots)

# Custom CSS
st.markdown("""
<style>
.main-header {
    background: linear-gradient(90deg, #4CAF50, #45a049);
    padding: 1rem;
    border-radius: 10px;
    margin-bottom: 2rem;
}
.metric-card {
    background: #f0f2f6;
    padding: 1rem;
    border-radius: 8px;
    border-left: 4px solid #4CAF50;
}
</style>
""", unsafe_allow_html=True)

# Main header
st.markdown("""
<div class="main-header">
    <h1 style="color: white; margin: 0;">🐸 Ultra Frog SEO Crawler</h1>
    <p style="color: white; margin: 0; opacity: 0.9;">by Amal Alexander - Professional SEO Analysis Tool</p>
</div>
""", unsafe_allow_html=True)

# Sidebar configuration
with st.sidebar:
    st.header("🔧 Crawl Configuration")
    
    # Crawl mode selection
    crawl_mode = st.selectbox("🎯 Crawl Mode", [
        "🕷️ Spider Crawl (Follow Links)",
        "📝 List Mode (Upload URLs)",
        "🗺️ Sitemap Crawl (XML Sitemap)"
    ])
    
    if crawl_mode == "🕷️ Spider Crawl (Follow Links)":
        start_url = st.text_input("🌐 Website URL", placeholder="https://example.com")
        max_urls = st.number_input("📊 Max URLs to crawl", min_value=1, max_value=100000, value=1000)
        
    elif crawl_mode == "📝 List Mode (Upload URLs)":
        st.markdown("**Upload a text file with URLs (one per line)**")
        uploaded_file = st.file_uploader("Choose file", type=['txt', 'csv'])
        url_list_text = st.text_area("Or paste URLs here (one per line)", height=100, 
                                   placeholder="https://example.com/page1\nhttps://example.com/page2")
        
    elif crawl_mode == "🗺️ Sitemap Crawl (XML Sitemap)":
        sitemap_url = st.text_input("🗺️ Sitemap URL", placeholder="https://example.com/sitemap.xml")
        max_urls = st.number_input("📊 Max URLs from sitemap", min_value=1, max_value=100000, value=5000)
    
    # Advanced options
    st.markdown("### ⚙️ Advanced Options")
    ignore_robots = st.checkbox("🤖 Ignore robots.txt", help="Crawl URLs even if blocked by robots.txt")
    
    col1, col2 = st.columns(2)
    with col1:
        start_btn = st.button("🚀 Start Crawl", type="primary", disabled=st.session_state.crawling)
    with col2:
        stop_btn = st.button("⛔ Stop Crawl", disabled=not st.session_state.crawling)
    
    if start_btn:
        # Validate inputs based on mode
        valid_input = False
        url_list = []
        
        if crawl_mode == "🕷️ Spider Crawl (Follow Links)" and start_url:
            valid_input = True
            
        elif crawl_mode == "📝 List Mode (Upload URLs)":
            if uploaded_file:
                content = uploaded_file.read().decode('utf-8')
                url_list = [line.strip() for line in content.split('\n') if line.strip()]
                valid_input = len(url_list) > 0
            elif url_list_text:
                url_list = [line.strip() for line in url_list_text.split('\n') if line.strip()]
                valid_input = len(url_list) > 0
                
        elif crawl_mode == "🗺️ Sitemap Crawl (XML Sitemap)" and sitemap_url:
            valid_input = True
        
        if valid_input:
            st.session_state.crawling = True
            st.session_state.stop_crawling = False
            st.session_state.crawl_data = []
            st.session_state.visited_urls = set()
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            try:
                with st.spinner("🐸 Ultra Frog is crawling..."):
                    if crawl_mode == "🕷️ Spider Crawl (Follow Links)":
                        crawl_data = crawl_website(start_url, max_urls, progress_bar, status_text, ignore_robots)
                    elif crawl_mode == "📝 List Mode (Upload URLs)":
                        crawl_data = crawl_from_list(url_list, progress_bar, status_text, ignore_robots)
                    else:  # Sitemap crawl
                        crawl_data = crawl_from_sitemap(sitemap_url, max_urls, progress_bar, status_text, ignore_robots)
                    
                    # Ensure crawl_data is not None
                    if crawl_data is None:
                        crawl_data = []
                    
                    st.session_state.crawl_data = crawl_data
                    st.session_state.crawling = False
                    st.session_state.stop_crawling = False
                
                if st.session_state.stop_crawling:
                    st.warning("⛔ Crawl stopped by user")
                else:
                    st.success(f"✅ Crawl completed! Found {len(crawl_data)} URLs")
                    
            except Exception as e:
                st.error(f"Error during crawling: {str(e)}")
                st.session_state.crawling = False
                st.session_state.stop_crawling = False
        else:
            st.error("Please provide valid input for the selected crawl mode")
    
    if stop_btn:
        st.session_state.stop_crawling = True
        st.session_state.crawling = False
    
    if st.button("🗑️ Clear All Data"):
        st.session_state.crawl_data = []
        st.session_state.visited_urls = set()
        st.rerun()
    
    st.markdown("---")
    st.markdown("### 🚀 Ultra Features")
    st.markdown("""
    - ✅ **3 Crawl Modes:** Spider, List, Sitemap
    - ✅ Stop/Resume crawling
    - 🤖 Ignore robots.txt option
    - 🔗 Canonical URL analysis
    - 📝 H1, H2, H3, H4 tags
    - 🌐 Open Graph & Twitter Cards
    - 📊 Schema markup detection
    - 🔄 Redirect chain analysis
    - 📈 Performance metrics
    - 🎯 Advanced SEO insights
    """)

# Main content area
if st.session_state.crawl_data:
    df = pd.DataFrame(st.session_state.crawl_data)
    
    # Enhanced summary stats
    st.header("📊 Ultra Frog Analysis Dashboard")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total URLs", len(df))
    with col2:
        indexable_count = len(df[df['indexability'] == 'Indexable'])
        st.metric("✅ Indexable", indexable_count)
    with col3:
        non_indexable_count = len(df[df['indexability'] == 'Non-Indexable'])
        st.metric("❌ Non-Indexable", non_indexable_count)
    with col4:
        redirect_count = len(df[df['redirect_count'] > 0])
        st.metric("🔄 Redirects", redirect_count)
    with col5:
        avg_response = df['response_time'].mean() if len(df) > 0 else 0
        st.metric("⚡ Avg Response", f"{avg_response:.2f}s")
    
    # Enhanced tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11 = st.tabs([
        "🔗 Internal", "🌐 External", "🖼️ Images", "📝 Titles", "📄 Meta Desc", 
        "🏷️ Headers", "🔄 Redirects", "📊 Status Codes", "🎯 Canonicals", "📱 Social", "🚀 Performance"
    ])
    
    with tab1:
        st.subheader("🔗 Internal Links Analysis")
        internal_df = df[['url', 'status_code', 'title', 'indexability', 'word_count', 'response_time']].copy()
        st.dataframe(internal_df, use_container_width=True)
        csv = internal_df.to_csv(index=False)
        st.download_button("📥 Download Internal Links", csv, "ultra_frog_internal.csv", "text/csv")
    
    with tab2:
        st.subheader("🌐 External Links Analysis")
        external_data = []
        for _, row in df.iterrows():
            for ext_link in row.get('external_links', []):
                external_data.append({
                    'source_url': row['url'],
                    'destination_url': ext_link['url'],
                    'anchor_text': ext_link['anchor_text']
                })
        
        if external_data:
            ext_df = pd.DataFrame(external_data)
            st.dataframe(ext_df, use_container_width=True)
            csv = ext_df.to_csv(index=False)
            st.download_button("📥 Download External Links", csv, "ultra_frog_external.csv", "text/csv")
        else:
            st.info("🔍 No external links found")
    
    with tab3:
        st.subheader("🖼️ Advanced Images Analysis")
        images_data = []
        for _, row in df.iterrows():
            for img in row.get('images', []):
                images_data.append({
                    'source_url': row['url'],
                    'image_url': img['src'],
                    'alt_text': img['alt'],
                    'title': img['title'],
                    'size_bytes': img['size_bytes'],
                    'dimensions': f"{img['width']}x{img['height']}" if img['width'] and img['height'] else 'Unknown'
                })
        
        if images_data:
            img_df = pd.DataFrame(images_data)
            st.dataframe(img_df, use_container_width=True)
            missing_alt = len(img_df[img_df['alt_text'] == ''])
            st.warning(f"⚠️ {missing_alt} images missing alt text")
            csv = img_df.to_csv(index=False)
            st.download_button("📥 Download Images Report", csv, "ultra_frog_images.csv", "text/csv")
        else:
            st.info("🔍 No images found")
    
    with tab4:
        st.subheader("📝 Page Titles Optimization")
        title_df = df[['url', 'title', 'title_length']].copy()
        title_df['status'] = title_df.apply(lambda row: 
            '❌ Missing' if row['title_length'] == 0 else
            '⚠️ Too Long' if row['title_length'] > 60 else
            '⚠️ Too Short' if row['title_length'] < 30 else '✅ Good', axis=1)
        
        st.dataframe(title_df, use_container_width=True)
        issues = len(title_df[~title_df['status'].str.contains('✅')])
        st.metric("🎯 Title Issues", issues)
        csv = title_df.to_csv(index=False)
        st.download_button("📥 Download Titles Report", csv, "ultra_frog_titles.csv", "text/csv")
    
    with tab5:
        st.subheader("📄 Meta Descriptions Analysis")
        meta_df = df[['url', 'meta_description', 'meta_desc_length']].copy()
        meta_df['status'] = meta_df.apply(lambda row: 
            '❌ Missing' if row['meta_desc_length'] == 0 else
            '⚠️ Too Long' if row['meta_desc_length'] > 160 else
            '⚠️ Too Short' if row['meta_desc_length'] < 120 else '✅ Good', axis=1)
        
        st.dataframe(meta_df, use_container_width=True)
        csv = meta_df.to_csv(index=False)
        st.download_button("📥 Download Meta Descriptions", csv, "ultra_frog_meta.csv", "text/csv")
    
    with tab6:
        st.subheader("🏷️ Header Tags Structure (H1-H4)")
        header_df = df[['url', 'h1_count', 'h2_count', 'h3_count', 'h4_count']].copy()
        header_df['h1_text'] = df['h1_tags'].apply(lambda x: ' | '.join(x[:2]) if x else 'Missing')
        header_df['h2_text'] = df['h2_tags'].apply(lambda x: f"{len(x)} H2 tags" if x else 'No H2')
        header_df['status'] = header_df.apply(lambda row: 
            '❌ No H1' if row['h1_count'] == 0 else
            '⚠️ Multiple H1' if row['h1_count'] > 1 else '✅ Good H1', axis=1)
        
        st.dataframe(header_df, use_container_width=True)
        csv = header_df.to_csv(index=False)
        st.download_button("📥 Download Headers Report", csv, "ultra_frog_headers.csv", "text/csv")
    
    with tab7:
        st.subheader("🔄 Redirect Chain Analysis")
        redirect_df = df[df['redirect_count'] > 0].copy()
        
        if not redirect_df.empty:
            redirect_display = redirect_df[['original_url', 'url', 'redirect_count', 'status_code']].copy()
            redirect_display.columns = ['Original URL', 'Final URL', 'Redirect Hops', 'Status Code']
            st.dataframe(redirect_display, use_container_width=True)
            
            chain_lengths = redirect_df['redirect_count'].value_counts()
            st.bar_chart(chain_lengths)
            csv = redirect_display.to_csv(index=False)
            st.download_button("📥 Download Redirects", csv, "ultra_frog_redirects.csv", "text/csv")
        else:
            st.info("✅ No redirects found - Great for SEO!")
    
    with tab8:
        st.subheader("📊 HTTP Status Code Analysis")
        status_counts = df['status_code'].value_counts().sort_index()
        
        col1, col2 = st.columns(2)
        with col1:
            st.bar_chart(status_counts)
        with col2:
            for status, count in status_counts.items():
                color = "🟢" if status == 200 else "🟡" if 300 <= status < 400 else "🔴"
                st.metric(f"{color} Status {status}", count)
        
        response_df = df[['url', 'status_code', 'indexability', 'response_time', 'server']].copy()
        st.dataframe(response_df, use_container_width=True)
        csv = response_df.to_csv(index=False)
        st.download_button("📥 Download Status Report", csv, "ultra_frog_status.csv", "text/csv")
    
    with tab9:
        st.subheader("🎯 Canonical URL Analysis")
        canonical_df = df[['url', 'canonical_url', 'meta_robots']].copy()
        canonical_df['canonical_status'] = canonical_df.apply(lambda row:
            '❌ Missing' if not row['canonical_url'] else
            '⚠️ Self-Referencing' if row['canonical_url'] == row['url'] else
            '🔄 Points Elsewhere', axis=1)
        
        st.dataframe(canonical_df, use_container_width=True)
        missing_canonical = len(canonical_df[canonical_df['canonical_url'] == ''])
        st.metric("⚠️ Missing Canonicals", missing_canonical)
        csv = canonical_df.to_csv(index=False)
        st.download_button("📥 Download Canonicals", csv, "ultra_frog_canonical.csv", "text/csv")
    
    with tab10:
        st.subheader("📱 Social Media Tags (OG & Twitter)")
        social_df = df[['url', 'og_title', 'og_description', 'og_image', 'twitter_title', 'twitter_description']].copy()
        social_df['og_complete'] = social_df.apply(lambda row: 
            '✅ Complete' if all([row['og_title'], row['og_description'], row['og_image']]) else '⚠️ Incomplete', axis=1)
        social_df['twitter_complete'] = social_df.apply(lambda row:
            '✅ Complete' if all([row['twitter_title'], row['twitter_description']]) else '⚠️ Incomplete', axis=1)
        
        st.dataframe(social_df, use_container_width=True)
        csv = social_df.to_csv(index=False)
        st.download_button("📥 Download Social Tags", csv, "ultra_frog_social.csv", "text/csv")
    
    with tab11:
        st.subheader("🚀 Performance & Technical Analysis")
        perf_df = df[['url', 'response_time', 'content_length', 'word_count', 'css_files', 'js_files', 'schema_count']].copy()
        perf_df['performance_score'] = perf_df.apply(lambda row:
            '🟢 Excellent' if row['response_time'] < 1.0 else
            '🟡 Good' if row['response_time'] < 3.0 else
            '🔴 Needs Improvement', axis=1)
        
        st.dataframe(perf_df, use_container_width=True)
        
        # Performance metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            avg_response = df['response_time'].mean()
            st.metric("⚡ Avg Response Time", f"{avg_response:.2f}s")
        with col2:
            avg_words = df['word_count'].mean()
            st.metric("📝 Avg Word Count", f"{int(avg_words)}")
        with col3:
            schema_pages = len(df[df['schema_count'] > 0])
            st.metric("🏷️ Pages with Schema", schema_pages)
        
        csv = perf_df.to_csv(index=False)
        st.download_button("📥 Download Performance Report", csv, "ultra_frog_performance.csv", "text/csv")

else:
    st.info("👈 Configure your crawl settings and click '🚀 Start Crawl' to begin Ultra Frog analysis")
    
    # Enhanced feature showcase
    st.markdown("### 🐸 Ultra Frog Features")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("""
        **🔧 Advanced Controls**
        - ⛔ Stop/Resume functionality
        - 🎯 100k URL capacity
        - ⚡ Multi-threaded crawling
        - 📊 Real-time progress
        """)
    
    with col2:
        st.markdown("""
        **📝 Complete SEO Analysis**
        - 🏷️ H1, H2, H3, H4 tags
        - 🎯 Canonical URL analysis
        - 🤖 Meta robots detection
        - 📱 Open Graph & Twitter Cards
        """)
    
    with col3:
        st.markdown("""
        **🔄 Advanced Features**
        - 🔗 Redirect chain tracking
        - 🏷️ Schema markup detection
        - 🖼️ Image optimization analysis
        - ⚡ Performance metrics
        """)
    
    with col4:
        st.markdown("""
        **📊 Professional Reports**
        - 📥 CSV exports for all data
        - 🎯 Issue identification
        - 📈 Performance scoring
        - 🔍 Technical SEO analysis
        """)

# Enhanced footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; padding: 2rem; background: linear-gradient(90deg, #4CAF50, #45a049); border-radius: 10px; margin-top: 2rem;">
    <h3 style="color: white; margin: 0;">🐸 Ultra Frog SEO Crawler</h3>
    <p style="color: white; margin: 0.5rem 0;">Created by <strong>Amal Alexander</strong></p>
    <p style="color: white; margin: 0; opacity: 0.9;">Professional SEO Analysis Tool - More Powerful Than Screaming Frog</p>
</div>
""", unsafe_allow_html=True)