from datetime import datetime , time
from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify
import random
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from razorpay import Client as RazorpayClient
from pyzbar.pyzbar import decode
from twilio.rest import Client as TwilioClient
import cv2
import os
import time as time_module

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Twilio Credentials
TWILIO_ACCOUNT_SID = "ACe24596da06700c639e5df4f9b0fb4fbb"
TWILIO_AUTH_TOKEN = "dc7401079c8e5a1f0e78003c0aa1b623"
TWILIO_mobile_number = "+16082004392"

client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Razorpay Credentials
RAZORPAY_KEY_ID = 'rzp_test_2xBwuSlxUQ23NX'
RAZORPAY_KEY_SECRET = 'h7KYg7Z5MVROyD9pYRnwSwyS'
razorpay_client = RazorpayClient(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


# Function to check if current time is within allowed payment hours
def is_payment_allowed():
    current_time = datetime.now().time()
    return current_time >= time(6, 0, 0) and current_time <= time(20, 0, 0)


# Function to generate and send OTP via SMS
def send_otp(mobile_number):
    otp = ''.join(random.choices('0123456789', k=6))
    session['expected_otp'] = otp
    session['mobile_number'] = mobile_number

    try:
        print(f"Sending OTP to {mobile_number}")
        message = client.messages.create(
            body=f'Your OTP is: {otp}',
            from_=TWILIO_mobile_number,
            to=f"+91{mobile_number}"  # Use the provided phone number
        )
        print(f"SMS sent successfully! Message ID: {message.sid}")
        return True, f'SMS sent successfully! Message ID: {message.sid}'
    except Exception as e:
        print(f"Failed to send SMS: {str(e)}")
        return False, f'Failed to send SMS: {str(e)}'

@app.route('/send_otp', methods=['POST'])
def send_otp_route():
    mobile_number = request.form.get('mobile_number')

    if not mobile_number:
        flash('Phone number is required.', 'error')
        return redirect(url_for('index'))

    success, message = send_otp(mobile_number)

    if success:
        flash('OTP sent successfully!', 'success')
        return redirect(url_for('verify_otp'))
    else:
        flash(f'Failed to send OTP: {message}', 'error')
        return redirect(url_for('index'))

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    if request.method == 'POST':
        entered_otp = request.form['otp']
        expected_otp = session.get('expected_otp')

        if entered_otp == expected_otp:
            flash('OTP verified successfully!', 'success')
            return redirect(url_for('pay'))
        else:
            flash('OTP verification failed. Please try again.', 'error')
            return redirect(url_for('verify_otp'))

    return render_template('otp_verification.html')

# Function to send email invoice
def send_invoice(email, amount):
    from_email = 'shukla20priyanka@gmail.com'  # Update with your Gmail email address
    from_password = 'vzsa hidh focw rlph'  # Update with your Gmail password

    if not email:
        print("Error: No recipient email address provided.")
        return False

    if not from_email or not from_password:
        print("Error: Email credentials are missing.")
        return False

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = email
    msg['Subject'] = 'Invoice for Your Payment'

    body = f"Thank you for your payment of ₹{amount}. Your order ID is {session.get('order_id')}. Here are the details:\n\n"
    body += f"Order ID: {session.get('order_id')}\n"
    body += f"Payment ID: {request.form.get('razorpay_payment_id')}\n"
    body += f"Signature: {request.form.get('razorpay_signature')}\n"

    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(from_email, from_password)
        text = msg.as_string()
        server.sendmail(from_email, email, text)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email: {str(e)}")
        return False

@app.route('/send_invoice', methods=['POST'])
def send_invoice_route():
    email = request.form.get('email')
    order_id = request.form.get('order_id')
    razorpay_payment_id = request.form.get('razorpay_payment_id')
    razorpay_order_id = request.form.get('razorpay_order_id')
    razorpay_signature = request.form.get('razorpay_signature')

    if not email:
        flash("Email address is required.", 'error')
        return redirect(url_for('success'))

    amount_in_paise = 1000  # Example amount, adjust as needed

    if send_invoice(email, amount_in_paise):
        flash("Invoice sent successfully to your email.", 'success')
    else:
        flash("Failed to send invoice. Please try again.", 'error')

    return redirect(url_for('index'))

# Function to process payment using Razorpay
def process_payment(qr_data, mobile_number):
    try:
        # Extract relevant information from QR data
        parsed_data = parse_qr_data(qr_data)
        print(f"Parsed QR data: {parsed_data}")

        if not parsed_data:
            return {"error": "Invalid QR code data format."}, None

        # Extracting and converting values from parsed QR data
        try:
            amount_in_paise = float(parsed_data.get('mc', 0))  # Amount in paise
            print(f"Amount in paise: {amount_in_paise}")
        except ValueError:
            print("Error converting 'mc' value to float.")
            return {"error": "Invalid amount in QR code data."}, None

        amount_in_inr = amount_in_paise / 100  # Convert to INR
        print(f"Amount in INR: {amount_in_inr}")

        payee_address = parsed_data.get('pa', '')
        transaction_reference = parsed_data.get('tr', '')
        customer_name = parsed_data.get('pn', '')

        if not is_payment_allowed():
            return {"error": "Payment is not allowed between 8 PM and 6 AM."}, None

        # Generate and send OTP
        success, message = send_otp(mobile_number)
        print(f"OTP sent: {success}, Message: {message}")

        return {"otp_generated": True}, success

    except Exception as e:
        print(str(e))
        return {"error": f"Error processing payment: {str(e)}"}, None

# Function to parse QR code data and return as a dictionary
def parse_qr_data(qr_data):
    try:
        parsed_data = {}
        components = qr_data.split('&')
        for component in components:
            key_value = component.split('=')
            parsed_data[key_value[0]] = key_value[1]
        return parsed_data
    except Exception as e:
        raise ValueError("Invalid QR code data format.")

# Function to scan QR code from webcam
def scan_qr_code():
    try:
        print("Starting QR code scan")
        cap = cv2.VideoCapture(0)
        qr_data = None

        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error: Failed to capture frame from webcam.")
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            qr_codes = decode(gray)
            print(f"Decoded QR codes: {qr_codes}")

            for qr_code in qr_codes:
                qr_data = qr_code.data.decode('utf-8')
                print(f"QR Code detected: {qr_data}")
                cap.release()
                cv2.destroyAllWindows()
                return qr_data

            cv2.imshow('Webcam', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            time_module.sleep(0.5)  # Use the time_module alias

        cap.release()
        cv2.destroyAllWindows()
        return qr_data
    except Exception as e:
        print(f"Error scanning QR code: {str(e)}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_qr_payment', methods=['POST'])
def process_qr_payment():
    try:
        mobile_number = request.form.get('mobile_number')

        # Validate mobile number
        if not mobile_number.isdigit() or len(mobile_number) != 10:
            flash("Invalid mobile number format. Please enter a valid 10-digit mobile number.", 'error')
            return redirect(url_for('index'))

        qr_data = scan_qr_code()
        if qr_data:
            result, otp = process_payment(qr_data, mobile_number)
            if 'error' in result:
                flash(result['error'], 'error')
            else:
                flash("QR Code scanned successfully. OTP has been sent to your mobile number.", 'success')
                return render_template('otp_verification.html', mobile_number=mobile_number)
        else:
            flash("No QR Code detected or decoded.", 'error')

        return redirect(url_for('index'))
    except Exception as e:
        flash(f"Error processing QR code payment: {str(e)}", 'error')
        return redirect(url_for('index'))

@app.route('/create_order', methods=['POST'])
def create_order():
    amount = request.json.get('amount')
    email = request.json.get('email')
    
    order_data = {
        'amount': amount,
        'currency': 'INR',
        'payment_capture': '1'
    }
    
    razorpay_order = razorpay_client.order.create(order_data)
    
    return jsonify({
        'order_id': razorpay_order['id'],
        'email': email
    })

@app.route('/pay', methods=['GET', 'POST'])
def pay():
    if request.method == 'POST':
        try:
            email = request.form.get('email')
            otp = request.form.get('otp')
            amount = 10000

            if not email or not otp:
                flash("Please provide an email and OTP.", 'error')
                return redirect(url_for('pay'))

            expected_otp = session.get('expected_otp')
            if otp != expected_otp:
                flash("Invalid OTP.", 'error')
                return redirect(url_for('pay'))

            order_data = {
                'amount': 50000,
                'currency': 'INR',
                'payment_capture': '1'
            }

            order = razorpay_client.order.create(data=order_data)
            razorpay_order_id = order['id']

            session.pop('expected_otp', None)  # Clear OTP from session after use

            send_invoice(email, amount)
            flash("Payment successful and invoice sent!", 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f"Error processing payment: {str(e)}", 'error')
            return redirect(url_for('pay'))
    return render_template('pay.html')

@app.route('/success', methods=['POST'])
def success():
    order_id = request.form.get('order_id')
    razorpay_payment_id = request.form.get('razorpay_payment_id')
    razorpay_order_id = request.form.get('razorpay_order_id')
    razorpay_signature = request.form.get('razorpay_signature')
    email = request.form.get('email')  # Get email from the form data
    
    print(f"Received email: {email}")
    
    if not email:
        flash("Email address is required to send the invoice.", 'error')
        return redirect(url_for('index'))

    amount_in_paise = 1000  # This should match the amount used in Razorpay options
    amount_in_inr = amount_in_paise / 100  # Convert to INR
    invoice_sent = send_invoice(email, amount_in_inr)
    
    if invoice_sent:
        flash("Invoice sent successfully to your email.", 'success')
    else:
        flash("Failed to send invoice. Please check your email settings.", 'error')

    return render_template('success.html', 
                           order_id=order_id, 
                           razorpay_payment_id=razorpay_payment_id, 
                           razorpay_order_id=razorpay_order_id, 
                           razorpay_signature=razorpay_signature)

if __name__ == '__main__':
    app.run(debug=True)
