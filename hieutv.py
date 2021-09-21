import os
import time
import json
import sys
import datetime
from selenium import webdriver
from google.cloud import firestore
from google.oauth2 import service_account
from jinja2 import Environment, FileSystemLoader, select_autoescape
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
import traceback
import logging

Log_Format = "%(levelname)s %(asctime)s - %(message)s"
logging.basicConfig(stream = sys.stdout,
                    format = Log_Format, 
                    level = logging.INFO)

DEV = os.environ.get('DEV')

COLLECTION_NAME = os.environ.get('COLLECTION_NAME')
DOCUMENT_ID = os.environ.get('DOCUMENT_ID')
GCP_PROJECT = os.environ.get('GCP_PROJECT')

if DEV:
    with open("credentials.json") as f:
        gcp_credentials = json.load(f)
else:
    gcp_credentials_str = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    gcp_credentials = json.loads(gcp_credentials_str)
gcp_credentials['private_key'] = gcp_credentials['private_key'].replace('\\n', '\n')
credentials = service_account.Credentials.from_service_account_info(gcp_credentials)

db = firestore.Client(credentials=credentials)
doc_ref = db.collection(COLLECTION_NAME).document(DOCUMENT_ID)

def extract_item(syllabus_item_element):
    return {
        "id": syllabus_item_element.get_attribute("id"),
        "header": syllabus_item_element.find_element_by_xpath('.//p[@class="syllabus__title"]').text.strip(),
        "url": syllabus_item_element.find_element_by_xpath('./a').get_attribute("href"),
    }

def send_email(to, subj, body):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = os.environ.get('SIB_API_KEY')

    subject = subj or "Send in blue"
    html_content = body
    sender = {"name":"HieuTV Notifier","email":"nghia@hieu.tv"}
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(to=to, html_content=html_content, sender=sender, subject=subject)

    try:
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))
        api_instance.send_transac_email(send_smtp_email)
    except ApiException as e:
        logging.error("Exception when calling SMTPApi->send_transac_email: %s\n" % e)

def send_template_email(template_path, to, subj, values):
    templateLoader = FileSystemLoader(searchpath="templates")
    env = Environment(
        loader=templateLoader,
        autoescape=select_autoescape(['html', 'xml'])
    )
    template = env.get_template(template_path)
    send_email(to, subj, template.render(**values))

def on_new_item(new_items):
    subj = "Chú tôi lên bài rồi"
    receivers = json.loads(os.environ.get('HIEUTV_MAILTO'))
    to = list(map(lambda email: {"email": email}, receivers))
    send_template_email("hieutv/mail.html", to, subj, {"items": new_items})

def on_failure(error):
    subj = "Lỗi Heroku"
    receivers = json.loads(os.environ.get('ERROR_MAILTO'))
    to = list(map(lambda email: {"email": email}, receivers))
    send_template_email("error.html", to, subj, {"error": error})

def set_record(item_ids):
    doc_ref.set({
        'last_update' : datetime.datetime.now(),
        'items': item_ids
    })

def get_record():
    doc = doc_ref.get()
    if not doc.exists:
        raise Exception("Document doesn't exist on Firestore")
    return doc.to_dict().get("items", list())

def check():
    if DEV:
        from msedge.selenium_tools import Edge, EdgeOptions
        options = EdgeOptions()
        options.use_chromium = True
        driver = Edge(options = options)
    else:
        options = webdriver.ChromeOptions()
        options.add_argument('--disable-gpu')
        options.add_argument('--headless')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')
        options.add_argument('window-size=1920x1080')
        options.binary_location = os.environ.get('GOOGLE_CHROME_PATH')
        driver = webdriver.Chrome(executable_path=os.environ.get('CHROMEDRIVER_PATH'), options=options)

    driver.get("https://www.hieu.tv/login")
    email_input = driver.find_element_by_xpath('//*[@id="member_email"]')
    password_input = driver.find_element_by_xpath('//*[@id="member_password"]')
    login_btn = driver.find_element_by_xpath('//*[@id="form-button"]')

    email_input.send_keys(os.environ.get('HIEUTV_USERNAME'))
    password_input.send_keys(os.environ.get('HIEUTV_PW'))
    login_btn.click()

    driver.get("https://www.hieu.tv/products/khoa-ck1")
    syllabus_item_elements = driver.find_elements_by_class_name("syllabus__item")

    syllabus_items = list(map(extract_item, syllabus_item_elements))

    old_item_ids = get_record()
    new_items = list(filter(lambda item: item["id"] not in old_item_ids, syllabus_items))
    all_item_ids = list(map(lambda x: x["id"], syllabus_items))
    set_record(all_item_ids)

    if len(new_items) > 0:
        logging.info("Found {} new items.".format(len(new_items)))
        on_new_item(new_items)
    else:
        logging.info("No new item found.")

    driver.quit()

def run_check():
    try:
        start_time = time.time()
        logging.info("Running check on hieu.tv")
        check()
        duration = time.time() - start_time
        logging.info("Checking completed on hieu.tv. Job took {:.2f}s".format(duration))
    except Exception as e:
        err = traceback.format_exc()
        logging.error(err)
        on_failure(err)

if __name__ == "__main__":
    run_check()