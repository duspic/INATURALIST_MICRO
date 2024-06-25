from flask import Flask, request, jsonify, url_for
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from apscheduler.schedulers.background import BackgroundScheduler
from typing import Optional
import logging
import os

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)

# Global variables to store API arguments, the previous result count, and subscription status
acc: Optional[bool] = None
identified: Optional[bool] = None
photos: Optional[bool] = None
taxon_name: Optional[str] = None
previous_result_count: Optional[int] = -1
job_id = 'daily_task'
scheduler = BackgroundScheduler()
is_subscribed = True

# Email configuration
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_USERNAME = 'duspic77@gmail.com'
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
EMAIL_FROM = 'duspic77@gmail.com'
EMAIL_TO = 'duspic77@gmail.com'
EMAIL_SUBJECT = 'iNaturalist Species Count Alert'

def send_email(message: str) -> None:
    """
    Sends an email notification with the given message.

    Args:
        message (str): The message to be sent in the email.
    """
    msg = MIMEMultipart()
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg['Subject'] = EMAIL_SUBJECT

    # Create an unsubscribe link
    unsubscribe_url = url_for('unsubscribe', _external=True)
    unsubscribe_html = f"<p>If you wish to unsubscribe, please click <a href='{unsubscribe_url}'>here</a>.</p>"

    # Attach the message and the unsubscribe link
    msg.attach(MIMEText(message + unsubscribe_html, 'html'))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        logging.info("Email sent successfully.")
    except smtplib.SMTPAuthenticationError:
        logging.error("SMTP authentication failed. Check your SMTP username and password.")
    except smtplib.SMTPException as e:
        logging.error(f"SMTP error occurred: {e}")
    except Exception as e:
        logging.error(f"An error occurred while sending email: {e}")

def check_species_count(acc: bool, identified: bool, photos: bool, taxon_name: str) -> None:
    """
    Checks the species count from the iNaturalist API and compares it with the previous count.

    Args:
        acc (bool): Whether to include accurate results.
        identified (bool): Whether to include identified results.
        photos (bool): Whether to include results with photos.
        taxon_name (str): The taxon name to search for.
    """
    global previous_result_count  # Declare as global to modify it

    # Construct the API URL with the given parameters
    url = "https://api.inaturalist.org/v1/observations/species_counts"
    params = {
        "acc": str(acc).lower(),
        "identified": str(identified).lower(),
        "photos": str(photos).lower(),
        "taxon_name": taxon_name
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx and 5xx)
        data = response.json()

        if 'total_results' not in data:
            logging.error("Unexpected API response format.")
            return

        total_results = data['total_results']
        logging.info(f"Total results: {total_results}")

        if previous_result_count is not None and total_results > previous_result_count:
            msg = f"""
            {total_results - previous_result_count} New observations of '{taxon_name}'
            Currently, {total_results} observations are available in the iNaturalist app!
            """
            send_email(msg)

        previous_result_count = total_results
    except requests.RequestException as e:
        logging.error(f"Request to iNaturalist API failed: {e}")

def daily_task() -> None:
    """
    Scheduled task to run daily and check the species count.
    """
    global acc, identified, photos, taxon_name  # Declare as global to use them

    if None in [acc, identified, photos, taxon_name]:
        logging.info("API parameters are not set.")
        return

    check_species_count(acc, identified, photos, taxon_name)

@app.route('/update', methods=['POST'])
def update() -> jsonify:
    """
    Endpoint to update API parameters and reset the previous result count.

    Returns:
        jsonify: JSON response indicating the status of the update.
    """
    global acc, identified, photos, taxon_name, previous_result_count, is_subscribed  # Declare as global to modify them

    try:
        acc = request.json['acc']
        identified = request.json['identified']
        photos = request.json['photos']
        taxon_name = request.json['taxon_name']

        # Reset previous result count
        previous_result_count = 0

        # Immediately check with new parameters
        check_species_count(acc, identified, photos, taxon_name)

        # Start the job if it was stopped
        if not is_subscribed:
            scheduler.add_job(daily_task, 'cron', hour=8, minute=0, timezone='GMT', id=job_id)
            is_subscribed = True
            logging.info("Rescheduled daily task.")

        return jsonify({"status": "success"}), 200
    except KeyError as e:
        return jsonify({"error": f"Missing parameter: {e}"}), 400

@app.route('/unsubscribe', methods=['GET'])
def unsubscribe() -> str:
    """
    Endpoint to unsubscribe from the daily email updates.

    Returns:
        str: HTML response indicating the status of the unsubscription.
    """
    global is_subscribed  # Declare as global to modify it

    if is_subscribed:
        scheduler.remove_job(job_id)
        is_subscribed = False
        logging.info("Unsubscribed from daily task.")
        return "<p>You have successfully unsubscribed from daily updates.</p>"
    else:
        return "<p>You are already unsubscribed.</p>"

if __name__ == '__main__':
    scheduler.add_job(daily_task, 'interval', seconds=15, timezone='GMT', id=job_id)
    scheduler.start()

    try:
        port = int(os.environ.get("PORT", 5000))
        app.run(host='0.0.0.0', port=port)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
