#1022038010.py
from flask import Flask, request, jsonify, render_template
import requests 
import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
import mimetypes
import zipfile
import io
from dotenv import load_dotenv 

load_dotenv()

app = Flask(__name__, template_folder='../templates')

logging.basicConfig(level=logging.DEBUG)

API_KEY = os.getenv('GOOGLE_API_KEY')
CX = os.getenv('GOOGLE_CX')

SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = int(os.getenv('SMTP_PORT'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
CUSTOM_USER_AGENT = os.getenv('CUSTOM_USER_AGENT')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_and_send_images', methods=['POST'])
def search_and_send_images():
    query = request.json.get('query')
    num_images = min(int(request.json.get('num_images', 100)), 100)  
    email = request.json.get('email')
    send_as_zip = request.json.get('send_as_zip', False)

    if not query or not email:
        return jsonify({"error": "Missing query or email"}), 400

    try:
        image_urls = fetch_image_urls(query, num_images * 2)
        logging.debug(f"Fetched {len(image_urls)} image URLs")

        downloaded_images = download_images(image_urls, num_images)
        logging.debug(f"Downloaded {len(downloaded_images)} images")

        sent_images = send_email_with_attachments(email, query, downloaded_images, num_images, send_as_zip)
        logging.info(f"Email sent to {email} with {sent_images} images")

        return jsonify({
            "message": f"Sent {sent_images} images for query '{query}' to {email}",
            "image_urls": [img['url'] for img in downloaded_images[:sent_images]]
        }), 200
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

def fetch_image_urls(query, num_images):
    url = "https://www.googleapis.com/customsearch/v1"
    all_image_urls = []
    
    for start_index in range(1, min(num_images + 1, 101), 10):
        params = {
            'q': query,
            'num': min(10, num_images - len(all_image_urls)),
            'start': start_index,
            'imgSize': 'medium',
            'searchType': 'image',
            'key': API_KEY,
            'cx': CX
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            results = response.json()
            all_image_urls.extend([item['link'] for item in results.get('items', [])])
            
            if len(all_image_urls) >= num_images:
                break
        except requests.RequestException as e:
            logging.error(f"Error fetching image URLs: {str(e)}")
    
    return all_image_urls[:num_images]

def validate_image_url(url, headers):
    try:
        response = requests.head(url, headers=headers, timeout=5)
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '')
            if content_type.startswith('image/'):
                return True
        return False
    except requests.RequestException:
        return False

def download_images(image_urls, num_images):
    downloaded_images = []
    headers = {'User-Agent': CUSTOM_USER_AGENT}

    for url in image_urls:
        if len(downloaded_images) >= num_images:
            break
        if not validate_image_url(url, headers):
            logging.warning(f"Skipped invalid or unavailable image: {url}")
            continue
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            content_type = response.headers.get('content-type', '').split('/')
            if len(content_type) > 1 and content_type[0] == 'image':
                image_type = content_type[1]
                if len(response.content) > 0:
                    downloaded_images.append({
                        'url': url,
                        'content': response.content,
                        'type': image_type
                    })
                else:
                    logging.warning(f"Skipped image: {url}. Empty content.")
            else:
                logging.warning(f"Skipped image: {url}. Not a valid image type.")
        except requests.HTTPError as e:
            logging.warning(f"Failed to download image: {url}. HTTP Error: {str(e)}")
        except requests.RequestException as e:
            logging.warning(f"Failed to download image: {url}. Error: {str(e)}")

    return downloaded_images

def send_email_with_attachments(to_email, query, images, num_images, send_as_zip):
    msg = MIMEMultipart()
    msg['From'] = SMTP_USERNAME
    msg['To'] = to_email
    msg['Subject'] = f"Images for: {query}"

    text = MIMEText(f"Here are the images for your search: {query}")
    msg.attach(text)

    sent_images = 0
    if send_as_zip:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for i, img in enumerate(images):
                if sent_images >= num_images:
                    break
                try:
                    zip_file.writestr(f"image_{i+1}.{img['type']}", img['content'])
                    sent_images += 1
                except Exception as e:
                    logging.warning(f"Failed to add image {i+1} to zip: {str(e)}")

        zip_attachment = MIMEApplication(zip_buffer.getvalue())
        zip_attachment.add_header('Content-Disposition', 'attachment', filename=f"{query}_images.zip")
        msg.attach(zip_attachment)
    else:
        for i, img in enumerate(images):
            if sent_images >= num_images:
                break
            try:
                image = MIMEImage(img['content'], _subtype=img['type'])
                image.add_header('Content-Disposition', 'attachment', filename=f"image_{i+1}.{img['type']}")
                msg.attach(image)
                sent_images += 1
            except Exception as e:
                logging.warning(f"Failed to attach image {i+1}: {str(e)}")

    if sent_images < num_images:
        text = MIMEText(f"\n\nNote: Only {sent_images} out of {num_images} requested images were available and included.")
        msg.attach(text)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return sent_images
    except smtplib.SMTPException as e:
        logging.error(f"Failed to send email: {str(e)}")
        raise

if __name__ == '__main__':
    app.run(debug=True)

app = app
