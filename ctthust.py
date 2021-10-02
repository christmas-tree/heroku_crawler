import os
import time
import json
import sys
from selenium import webdriver
from google.oauth2 import service_account
from googleapiclient.discovery import build
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
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
SPREADSHEET_RANGE = os.environ.get('SPREADSHEET_RANGE')
COLS = {
    'term': 0,
    'course_name': 1,
    'course_id': 2,
    'course_credit': 3,
    'mid_score': 4,
    'end_score': 5,
    'course_weight': 6,
}

if DEV:
    with open("credentials.json") as f:
        gcp_credentials = json.load(f)
else:
    gcp_credentials_str = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    gcp_credentials = json.loads(gcp_credentials_str)
gcp_credentials['private_key'] = gcp_credentials['private_key'].replace('\\n', '\n')
credentials = service_account.Credentials.from_service_account_info(gcp_credentials)


def send_email(to, subj, body):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = os.environ.get('SIB_API_KEY')

    subject = subj or "Send in blue"
    html_content = body
    sender = {"name":"CTTHust Notifier","email":"nghia@nghia.tv"}
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
    subj = "Có cập nhật điểm!"
    receivers = json.loads(os.environ.get('CTTHUST_MAILTO'))
    to = list(map(lambda email: {"email": email}, receivers))
    send_template_email("ctthust/mail.html", to, subj, {"items": new_items})

def on_failure(error):
    subj = "Lỗi Heroku"
    receivers = json.loads(os.environ.get('ERROR_MAILTO'))
    to = list(map(lambda email: {"email": email}, receivers))
    send_template_email("error.html", to, subj, {"error": error})

def update_sheet_records(values):
    sheets = service.spreadsheets()
    body = {
        "majorDimension": "ROWS",
        "values": values,
    }
    records = sheets.values().update(spreadsheetId=SPREADSHEET_ID, range=SPREADSHEET_RANGE, body=body, valueInputOption="USER_ENTERED").execute()
    return records

def fetch_sheet_records():
    sheets = service.spreadsheets()
    records = sheets.values().get(spreadsheetId=SPREADSHEET_ID, range=SPREADSHEET_RANGE, valueRenderOption='FORMULA').execute()
    return records

def set_record_attribute(record, attribute, value):
    idx = COLS[attribute]
    while len(record) < idx + 1:
        record.append('')
    if not value:
        return False
    old_value = record[idx]
    record[idx] = value
    return str(old_value) != str(value)

def set_record(record, item):
    changed = False
    changed = set_record_attribute(record, 'course_name', item.get('course_name', '')) or changed
    changed = set_record_attribute(record, 'term', item.get('term', '')) or changed
    changed = set_record_attribute(record, 'course_credit', item.get('course_credit', '')) or changed
    changed = set_record_attribute(record, 'mid_score', item.get('mid_score', '')) or changed
    changed = set_record_attribute(record, 'end_score', item.get('end_score', '')) or changed
    changed = set_record_attribute(record, 'course_weight', item.get('course_weight', '')) or changed
    return changed

def convert_item_to_dict(item_arr):
    item = {}
    for attribute in COLS.keys():
        idx = COLS[attribute]
        if idx >= len(item_arr):
            item[attribute] = ''
            continue
        item[attribute] = item_arr[idx]
    return item

def extract_item_full(row):
    return {
        "term": row.find_element_by_xpath('./td[1]').text.strip(),
        "course_id": row.find_element_by_xpath('./td[2]').text.strip(),
        "course_name": row.find_element_by_xpath('./td[3]').text.strip(),
        "course_credit": row.find_element_by_xpath('./td[4]').text.strip(),
        "class_id": row.find_element_by_xpath('./td[5]').text.strip(),
        "mid_score": row.find_element_by_xpath('./td[6]').text.strip(),
        "end_score": row.find_element_by_xpath('./td[7]').text.strip(),
    }

def extract_item_temp(row):
    return {
        "class_id": row.find_element_by_xpath('./td[2]').text.strip(),
        "course_name": row.find_element_by_xpath('./td[3]').text.strip(),
        "course_weight": str(1 - float(row.find_element_by_xpath('./td[4]').text.strip())),
        "mid_score": row.find_element_by_xpath('./td[5]').text.strip(),
        "end_score":row.find_element_by_xpath('./td[7]').text.strip(),
    }

def check():
    if DEV:
        from msedge.selenium_tools import Edge, EdgeOptions
        options = EdgeOptions()
        options.use_chromium = True
        driver = Edge(options = options)
        driver.set_window_size(1920, 1080)
    else:
        options = webdriver.ChromeOptions()
        options.add_argument('--disable-gpu')
        options.add_argument('--headless')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')
        options.add_argument('window-size=1920x1080')
        options.binary_location = os.environ.get('GOOGLE_CHROME_PATH')
        driver = webdriver.Chrome(executable_path=os.environ.get('CHROMEDRIVER_PATH'), options=options)

    driver.get("https://ctt.hust.edu.vn/")
    driver.find_element_by_xpath('//a[@id="loginLink"]').click()

    email_input = driver.find_element_by_xpath('//input[@id="userNameInput"]')
    email_input.send_keys(os.environ.get('CTTHUST_USERNAME'))

    driver.find_element_by_xpath('//span[@id="nextButton"]').click()
    time.sleep(0.5)

    password_input = driver.find_element_by_xpath('//*[@id="passwordInput"]')
    password_input.send_keys(os.environ.get('CTTHUST_PW'))
    time.sleep(0.5)
    driver.find_element_by_xpath('//span[@id="submitButton"]').click()
    time.sleep(2)
    driver.get("https://dt-ctt.hust.edu.vn/Students/StudentCourseMarks.aspx")
    time.sleep(1)

    rows = driver.find_elements_by_xpath('//table[contains(@id, "gvCourseMarks")]//tr[@class="dxgvDataRow"]')
    items = list(map(extract_item_full, rows))
    logging.info("items: {}".format(items))
    driver.get("https://dt-ctt.hust.edu.vn/Students/StudentCheckInputGradeTerm.aspx")
    rows = driver.find_elements_by_xpath('//table[contains(@id, "gvClassGrade")]//tr[contains(@class, "dxgvDataRow")]')
    temp_items = list(map(extract_item_temp, rows))
    logging.info("temp_items: {}".format(temp_items))

    changed_records = []
    records = fetch_sheet_records().get("values")
    logging.info("records: {}".format(records))

    record_dict = dict()
    for record in records:
        course_id = record[COLS['course_id']]
        course_records = record_dict.get(course_id, [])
        course_records.append(record)
        record_dict[course_id] = course_records
    
    for item in items:
        record = None
        if item['course_id'] in record_dict:
            course_records = record_dict.get(item['course_id'])
            for course_record in course_records:
                if str(course_record[COLS["term"]]) == str(item['term']):
                    record = course_record
                    break
        if not record:
            record = []
            records.append(record)
        changed = set_record(record, item)
        if changed:
            changed_records.append(record)
        
    record_dict = dict()
    for record in records:
        course_name = record[COLS['course_name']]
        course_records = record_dict.get(course_name, [])
        course_records.append(record)
        record_dict[course_name] = course_records
    for item in temp_items:
        record = None
        if item['course_name'] in record_dict:
            course_records = record_dict.get(item['course_name'])
            max_term = 0
            for course_record in course_records:
                if int(course_record[COLS["term"]]) > max_term:
                    record = course_record
                    max_term = int(course_record[COLS["term"]])
        if not record:
            record = []
            records.append(record)
        changed = set_record(record, item)
        if changed:
            changed_records.append(record)
    
    driver.quit()
    if len(changed_records) == 0:
        logging.info("No new item found.")
        return
    
    logging.info("Found {} new items: {}".format(len(changed_records), changed_records))
    update_sheet_records(records)
    changed_records_arr = changed_records
    changed_records = map(lambda record: convert_item_to_dict(record), changed_records_arr)
    on_new_item(changed_records)


def run_check():
    global service
    try:
        start_time = time.time()
        logging.info("Running check on ctthust")

        service = build('sheets', 'v4', credentials=credentials)
        check()
        service.close()

        duration = time.time() - start_time
        logging.info("Checking completed on ctthust. Job took {:.2f}s".format(duration))
    except Exception as e:
        err = traceback.format_exc()
        logging.error(err)
        on_failure(err)

if __name__ == "__main__":
    run_check()