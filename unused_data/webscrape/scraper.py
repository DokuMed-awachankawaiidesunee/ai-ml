from bs4 import BeautifulSoup
import csv
import time
from urllib.parse import urljoin, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

INITIAL_SEED_URLS = [
    "https://www.bpjs-kesehatan.go.id/",
    "https://www.bpjs-kesehatan.go.id/#/",
    "https://www.bpjs-kesehatan.go.id/#/profil",
    "https://bpjs-kesehatan.go.id/#/jaminan",
    "https://bpjs-kesehatan.go.id/#/layanan",

    "https://bpjs-kesehatan.go.id/user-manual-mobile-jkn/"
]
TARGET_DOMAIN = "bpjs-kesehatan.go.id"
OUTPUT_CSV_FILE = "bpjs_kesehatan_data_selenium.csv"
REQUEST_DELAY_SECONDS = 3
REQUEST_TIMEOUT_SECONDS = 30
JS_RENDER_WAIT_SECONDS = 5

WEBDRIVER_PATH = 'C:/Users/Salsabiila/OneDrive/Comp/chromedriver.exe' # Keep your path
driver_service_obj = ChromeService(executable_path=WEBDRIVER_PATH)


def fetch_page_content_selenium(driver, url):
    try:
        print(f"Fetching with Selenium: {url}")
        driver.get(url)
        WebDriverWait(driver, REQUEST_TIMEOUT_SECONDS).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        if "#" in urlparse(url).fragment:
            print(f"Fragment URL detected: {url}. Allowing up to {JS_RENDER_WAIT_SECONDS}s for JS rendering.")
            try:
                common_fragment_content_selectors = [
                    (By.CSS_SELECTOR, "div.container-view"),
                    (By.CSS_SELECTOR, "router-view"),
                    (By.ID, "content"),
                    (By.CLASS_NAME, "page-content"),
                ]
                element_found = False
                for locator_strategy, selector_value in common_fragment_content_selectors:
                    try:
                        WebDriverWait(driver, JS_RENDER_WAIT_SECONDS).until(
                            EC.visibility_of_element_located((locator_strategy, selector_value))
                        )
                        print(f"Specific content container '{selector_value}' for fragment loaded.")
                        element_found = True
                        break
                    except TimeoutException:
                        continue
                if not element_found:
                    print(f"No specific fragment container found quickly. Relying on page source after general wait.")
            except Exception as e_wait:
                print(f"Error during specific wait for fragment content on {url}: {e_wait}")
                time.sleep(JS_RENDER_WAIT_SECONDS / 2)


        return driver.page_source
    except TimeoutException:
        print(f"Timeout loading page with Selenium: {url}")
    except WebDriverException as e:
        print(f"WebDriverException fetching {url}: {e}")
        if "net::ERR_NAME_NOT_RESOLVED" in str(e) or "dns" in str(e).lower():
            print(f"DNS resolution error for {url}. Skipping.")
        elif "Reached error page" in str(e):
            print(f"Reached an error page for {url}. Skipping.")
    except Exception as e:
        print(f"Generic error fetching with Selenium {url}: {e}")
    return None

def extract_meaningful_text(soup_element):
    """Extracts text from a BeautifulSoup element, trying to be a bit cleaner."""
    if not soup_element:
        return ""
    for script_or_style in soup_element(["script", "style", "header", "footer", "nav", "aside", "form", "button", "input", "img", "figure", "figcaption", "iframe", "svg", "path"]):
        script_or_style.decompose()
    text = soup_element.get_text(separator='\n', strip=True)
    text = '\n'.join([line.strip() for line in text.splitlines() if line.strip() and len(line.strip()) > 1]) # Ensure lines have some substance
    return text

def parse_content(html_content, url):
    """Parses HTML content to extract relevant information."""
    soup = BeautifulSoup(html_content, 'html.parser')
    extracted_data = []
    page_title_tag = soup.find('title')
    page_title = page_title_tag.string.strip() if page_title_tag else "No Title Found"

    main_content_selectors = [
        'div.container-view',
        'div.content-inner',
        'article.article-detail',
        'div.berita-detail-konten',
        'article', 'main',
        'div[class*="content"]', 'div[class*="post"]', 'div[class*="konten"]',
        'div[class*="berita"]', 'div[class*="isi"]', 'div[class*="detail"]',
        'div[id*="content"]', 'div[id*="main"]', 'div[id*="artikel"]'
    ]
    content_found_specific = False
    for selector in main_content_selectors:
        elements = soup.select(selector)
        for i, element in enumerate(elements):
            is_likely_primary = not any(parent.select_one(selector) for parent in element.parents if parent != soup) or i == 0

            text_content = extract_meaningful_text(element)
            if len(text_content) > 150:
                specific_title = page_title
                h1 = element.find('h1')
                if h1 and h1.string: specific_title = extract_meaningful_text(h1)
                else:
                    h2 = element.find('h2')
                    if h2 and h2.string: specific_title = extract_meaningful_text(h2)

                extracted_data.append({
                    "source_url": url, "title": specific_title,
                    "content_type": f"selector:{selector}", "content_text": text_content
                })
                content_found_specific = True
        if content_found_specific: break

    faq_items_found = 0
    dts = soup.find_all('dt')
    for dt in dts:
        question = extract_meaningful_text(dt)
        dd = dt.find_next_sibling('dd')
        answer = extract_meaningful_text(dd) if dd else ""
        if question and answer and len(answer) > 10:
            extracted_data.append({
                "source_url": url, "title": f"FAQ: {question[:100].strip('.')}{'...' if len(question) > 100 else ''}",
                "content_type": "faq_dt_dd", "content_text": f"Question: {question}\nAnswer: {answer}"
            })
            faq_items_found +=1

    for i in range(2, 5):
        headings = soup.find_all(f'h{i}')
        for heading in headings:
            question = extract_meaningful_text(heading)
            is_potential_question = '?' in question or (len(question.split()) < 15 and len(question.split()) > 1 and question.strip().endswith(('.', ':', '!')) is False)

            if question and is_potential_question:
                next_element = heading.find_next_sibling()
                answer_parts = []
                elements_for_answer = 0
                while next_element and elements_for_answer < 5:
                    if next_element.name in [f'h{j}' for j in range(1,7)]: break
                    if next_element.name in ['p', 'div', 'ul', 'ol', 'span', 'li', 'table']:
                        part_text = extract_meaningful_text(next_element)
                        if part_text:
                            answer_parts.append(part_text)
                            elements_for_answer +=1
                    next_element = next_element.find_next_sibling()

                answer = "\n".join(filter(None, answer_parts))
                if answer and len(answer) > 20:
                    extracted_data.append({
                        "source_url": url, "title": f"FAQ: {question[:100].strip('.')}{'...' if len(question) > 100 else ''}",
                        "content_type": f"faq_h{i}_sibling", "content_text": f"Question: {question}\nAnswer: {answer}"
                    })
                    faq_items_found +=1

    if not (content_found_specific or faq_items_found > 0):
        body_element = soup.find('body')
        fallback_selectors = ['div[role="main"]', 'div.main-container', 'div#app', 'div.page']
        body_text_element = None
        fs_selector_used = "body_direct"

        if body_element:
            for fs_selector in fallback_selectors:
                potential_element = body_element.select_one(fs_selector)
                if potential_element:
                    body_text_element = potential_element
                    fs_selector_used = fs_selector
                    print(f"Using fallback selector '{fs_selector}' for body text on {url}")
                    break
            if not body_text_element:
                 body_text_element = body_element

        if body_text_element:
            body_text = extract_meaningful_text(body_text_element)
            if body_text and len(body_text) > 100:
                extracted_data.append({
                    "source_url": url, "title": page_title,
                    "content_type": f"body_fallback:{fs_selector_used}", "content_text": body_text
                })
            elif body_text:
                 print(f"Fallback body text for {url} was too short ({len(body_text)} chars).")


    if not extracted_data:
        print(f"No content extracted from {url} by parsing logic (page might be empty, structure not recognized, or text too short).")
    return extracted_data

def find_links(html_content, base_url, target_domain):
    """Finds all valid links on the page that belong to the target domain."""
    soup = BeautifulSoup(html_content, 'html.parser')
    links = set()
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        if not href or href.lower().startswith('javascript:') or href.lower().startswith('mailto:'):
            continue

        if href == "#":
            continue

        full_url = urljoin(base_url, href)
        parsed_url = urlparse(full_url)

        normalized_path = parsed_url.path.rstrip('/') if parsed_url.path else '/'

        check_url_parts = parsed_url._replace(path=normalized_path, query="")
        final_url_to_add = check_url_parts.geturl()


        if parsed_url.scheme in ['http', 'https'] and \
           (parsed_url.netloc == target_domain or parsed_url.netloc.endswith('.' + target_domain)):
            if not any(parsed_url.path.lower().endswith(ext) for ext in [
                '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.zip', '.doc', '.docx',
                '.xls', '.xlsx', '.ppt', '.pptx', '.mp3', '.mp4', '.avi', '.exe',
                '.dmg', '.pkg', '.rss', '.xml', '.css', '.js', '.json', '.txt', '.woff', '.ttf', '.svg', '.ico'
            ]):
                links.add(final_url_to_add)
    return list(links)

def save_to_csv(data_list, filename):
    """Saves the extracted data to a CSV file."""
    if not data_list: return
    fieldnames = ["source_url", "title", "content_type", "content_text"]
    file_exists = False
    try:
        with open(filename, 'r', newline='', encoding='utf-8') as f_check:
            if f_check.readline(): file_exists = True
    except FileNotFoundError: pass

    with open(filename, 'a' if file_exists else 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        if not file_exists: writer.writeheader()
        for item in data_list:
            writer.writerow({key: item.get(key, "") for key in fieldnames})
    print(f"{len(data_list)} items appended/saved to {filename}")

def normalize_url_for_set(url_string):
    """Normalizes a URL for consistent storage and checking in sets/logs."""
    p = urlparse(url_string)
    netloc = p.netloc.replace("www.", "")
    path = p.path.rstrip('/') if p.path else '/'
    return p._replace(scheme="https", netloc=netloc, path=path, query="", fragment=p.fragment).geturl()


def main():
    print("Initializing Selenium WebDriver...")
    driver = None
    try:
        print("Attempting to initialize ChromeDriver using Selenium Manager (default PATH)...")
        service_default = ChromeService()
        driver = webdriver.Chrome(service=service_default)
        print("ChromeDriver initialized successfully using Selenium Manager.")
    except Exception as e_path:
        print(f"Could not initialize ChromeDriver from PATH/Selenium Manager: {e_path}")
        try:
            print(f"Trying with specified WEBDRIVER_PATH: {WEBDRIVER_PATH}")
            driver = webdriver.Chrome(service=driver_service_obj)
            print("ChromeDriver initialized with specified WEBDRIVER_PATH.")
        except Exception as e_specific:
            print(f"CRITICAL: Could not initialize ChromeDriver with specified path: {e_specific}")
            print("Please ensure ChromeDriver is installed and WEBDRIVER_PATH is correctly set, or ChromeDriver is in your system PATH and compatible with your Chrome version.")
            return

    driver.set_page_load_timeout(REQUEST_TIMEOUT_SECONDS + JS_RENDER_WAIT_SECONDS)

    all_scraped_data_batch = []
    processed_urls_log_file = "selenium_processed_urls.log"
    processed_urls_set = set()

    try:
        with open(processed_urls_log_file, "r", encoding='utf-8') as f:
            for line in f:
                processed_urls_set.add(line.strip())
        print(f"Loaded {len(processed_urls_set)} processed URLs from {processed_urls_log_file}.")
    except FileNotFoundError:
        print(f"{processed_urls_log_file} not found. Starting fresh.")

    urls_to_visit_queue = []
    for seed_url in INITIAL_SEED_URLS:
        normalized_seed = normalize_url_for_set(seed_url)
        if normalized_seed not in processed_urls_set:
            urls_to_visit_queue.append(seed_url)
        else:
            print(f"Seed URL {seed_url} (normalized: {normalized_seed}) already processed.")


    max_urls_to_scrape = 500
    scraped_successfully_count = 0

    try:
        while urls_to_visit_queue and scraped_successfully_count < max_urls_to_scrape:
            current_url = urls_to_visit_queue.pop(0)
            normalized_current_url = normalize_url_for_set(current_url)

            if normalized_current_url in processed_urls_set:
                continue

            parsed_current = urlparse(current_url)
            current_domain = parsed_current.netloc
            if not (current_domain == TARGET_DOMAIN or current_domain.endswith('.' + TARGET_DOMAIN)):
                print(f"Skipping off-target-domain URL: {current_url}")
                processed_urls_set.add(normalized_current_url)
                continue

            print(f"Attempting ({scraped_successfully_count + 1}/{max_urls_to_scrape}): {current_url}")
            html_content = fetch_page_content_selenium(driver, current_url)

            processed_urls_set.add(normalized_current_url)

            if html_content:
                scraped_successfully_count += 1
                data_from_page = parse_content(html_content, current_url)
                if data_from_page:
                    all_scraped_data_batch.extend(data_from_page)
                    print(f"Extracted {len(data_from_page)} item(s) from {current_url}")

                new_links_found = find_links(html_content, current_url, TARGET_DOMAIN)
                for link in new_links_found:
                    normalized_link_for_check = normalize_url_for_set(link)
                    if normalized_link_for_check not in processed_urls_set and link not in urls_to_visit_queue:
                        is_already_queued = False
                        for q_item in urls_to_visit_queue:
                            if normalize_url_for_set(q_item) == normalized_link_for_check:
                                is_already_queued = True
                                break
                        if not is_already_queued:
                            urls_to_visit_queue.append(link)

                if len(all_scraped_data_batch) >= 5:
                    save_to_csv(all_scraped_data_batch, OUTPUT_CSV_FILE)
                    all_scraped_data_batch = []
                    with open(processed_urls_log_file, "w", encoding='utf-8') as f_log:
                        for purl in sorted(list(processed_urls_set)):
                            f_log.write(purl + "\n")

            else:
                print(f"Failed to fetch content for {current_url}. It remains marked as processed to avoid retries in this run.")


            print(f"Queue size: {len(urls_to_visit_queue)}. Processed unique URLs: {len(processed_urls_set)}.")
            time.sleep(REQUEST_DELAY_SECONDS)

    except KeyboardInterrupt:
        print("\nScraping interrupted by user.")
    except Exception as e_main:
        print(f"An unexpected error occurred in the main loop: {e_main}")
    finally:
        if all_scraped_data_batch:
            save_to_csv(all_scraped_data_batch, OUTPUT_CSV_FILE)

        with open(processed_urls_log_file, "w", encoding='utf-8') as f:
            for purl in sorted(list(processed_urls_set)):
                f.write(purl + "\n")

        if driver:
            print("Closing Selenium WebDriver...")
            driver.quit()

        print(f"Scraping finished or interrupted.")
        print(f"Total pages successfully fetched and processed in this run: {scraped_successfully_count}.")
        print(f"Total unique URLs logged as processed: {len(processed_urls_set)}.")
        print(f"Data saved to {OUTPUT_CSV_FILE}")
        print(f"Processed URLs log saved to {processed_urls_log_file}")

if __name__ == "__main__":
    main()