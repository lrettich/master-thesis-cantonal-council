# Azure imports
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

# General imports
import datetime
import logging
import os
import requests

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.wait import WebDriverWait

# Constants
WEB_DRIVER_LOCATION = '/usr/local/bin/chromedriver'
BASE_URL = 'https://www.kantonsrat.zh.ch/ratsbetrieb/sitzungenundprotokolle/'


# Main azure function
def main(mytimer: func.TimerRequest) -> None:
    
    # Azure default time logging
    utc_timestamp = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()
    if mytimer.past_due:
        logging.info('The timer is past due!')
    logging.info('Python timer trigger function ran at %s', utc_timestamp)

    # Create blob service client and container client
    storage_account_url = "https://" + os.environ["par_storage_account_name"] + ".blob.core.windows.net"
    client = BlobServiceClient(account_url=storage_account_url, credential=DefaultAzureCredential())

    # Configure webdriver for running in a docker container
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')

    # Initialize webdriver and open website
    driver = webdriver.Chrome(WEB_DRIVER_LOCATION, options=chrome_options)
    
    # The protocols are requested and scraped year by year.
    # If too much data would be requested, not all protocols are displayed by the website.
    # Start and end year are read from the function configuration.
    start_year = int(os.environ["par_function_start_year"])
    end_year = int(os.environ["par_function_end_year"])
    for year in range(start_year, end_year + 1):

        # Construct the url for requesting protocol data for a year and call it.
        params = [f'startDate={year}-01-01',
                  f'endDate={year}-12-31',
                  'sessionType=Kantonsrat']
        param_text = '&'.join(params)
        driver.get('?'.join((BASE_URL, param_text)))

        # Open all the agenda entries by clicking on the arrow.
        # WebDriverWait is necessary, because the page needs some time to load all these elements.
        for svg_element in WebDriverWait(driver, 15).until(ec.presence_of_all_elements_located((By.CLASS_NAME,
                                                                                                'AgendaEntry__svg'))):
            svg_element.click()

        # Loop over all "Download" buttons.
        count = 0
        skip_count = 0
        for download_button in driver.find_elements(By.CLASS_NAME, 'BBtn--download'):

            # Document should only be downloaded, if it is an actual protocol. Other documents should be ignored.
            if download_button.text == "Protokoll herunterladen (PDF)":

                # Collect values for the file name based on information in a parent html element.
                date = download_button.find_element(By.XPATH, '../../../..//div[@class="AgendaEntry__date"]').text
                day = date[:2]
                month = date[3:5]
                title = download_button.find_element(By.XPATH, '../../../..//div[@class="AgendaEntry__title"]').text
                title = title.replace(".", "")
                title = title.replace(" ", "_")

                # Construct the file name
                blob_name = f"{year}_{month}_{day}_{title}.pdf"

                # Request the URL of the pdf file, download the content of the pdf file. 
                response = requests.get(download_button.get_attribute('href'))

                # Check, if file is already present in the container
                blob_client = client.get_blob_client(container=os.environ["par_storage_container_name"], blob=blob_name)

                if not blob_client.exists():
                    count += 1

                    # Store file to the container
                    blob_client.upload_blob(response.content)
                else:
                    if (blob_client.download_blob().size != len(response.content)):
                        count += 1
                        blob_client.upload_blob(response.content, overwrite=True)
                    else:
                        skip_count += 1

        if skip_count > 0:
            skip_msg = f"Skipped {skip_count} already existing files."
        else:
            skip_msg = ""
        logging.info(f"Year {year}: Downloaded {count} files. {skip_msg}")