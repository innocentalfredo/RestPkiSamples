import os
import sys
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, make_response
from werkzeug import secure_filename
from lacunarestpki import *

# ----------------------------------------------------------------------------------------------------------
# PASTE YOUR ACCESS TOKEN BELOW
restpki_access_token = 'PLACE YOUR API ACCESS TOKEN HERE'
#                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# ----------------------------------------------------------------------------------------------------------

# Throw exception if token is not set (this check is here just for the sake of newcomers, you can remove it)
if ' API ' in restpki_access_token:
    raise Exception(
        'The API access token was not set! Hint: to run this sample you must generate an API access '
        'token on the REST PKI website and paste it on the file demo.py')

restpki_url = 'https://pki.rest/'
restpki_client = RestPkiClient(restpki_url, restpki_access_token)

# ----------------------------------------------------------------------------------------------------------
# APP SETTINGS
# ----------------------------------------------------------------------------------------------------------
if sys.version_info[0] < 3:
    reload(sys)
    sys.setdefaultencoding('utf-8')

UPLOAD_FOLDER = 'uploads'
STATIC_FOLDER = 'static'
ALLOWED_EXTENSIONS = set(['pdf'])
TEMPLATE_DOCUMENT = 'SampleDocument.pdf'

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['STATIC_FOLDER'] = STATIC_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


# ----------------------------------------------------------------------------------------------------------
# APP ROUTES
# ----------------------------------------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


# ----------------------------------------------------------------------------------------------------------
@app.route('/authentication')
def auth():
    # Get an instance of the Authentication class
    authentication = restpki_client.get_authentication()

    # Call the start_with_webpki() method, which initiates the authentication. This yields the "token", a 22-character
    # case-sensitive URL-safe string, which represents this authentication process. We'll use this value to call the
    # sign_with_rest_pki() method on the Web PKI component (see lacuna-web-pki-client.js) and also to call the complete
    # with_webpki() method on the route /authentication-action. This should not be mistaken with the API access token.
    try:
        token = authentication.start_with_webpki(StandardSecurityContexts.PKI_BRAZIL)
    except Exception as e:
        return render_template('error.html', msg=e)

    # Note: By changing the SecurityContext above you can accept only certificates from a certain PKI,
    # for instance, ICP-Brasil (StandardSecurityContexts.PKI_BRAZIL).

    # The token acquired above can only be used for a single authentication. In order to retry authenticating it is
    # necessary to get a new token. This can be a problem if the user uses the back button of the browser, since the
    # browser might show a cached page that we rendered previously, with a now stale token. To prevent this from
    # happening, we force page expiration through HTTP headers to prevent caching of the page.
    response = make_response(render_template('authentication.html', token=token))
    response.headers = get_expired_page_headers()
    return response


# ----------------------------------------------------------------------------------------------------------
@app.route('/authentication-action', methods=['POST'])
def auth_action():
    # Get the token for this authentication (rendered in a hidden input field, see authentication.html template)
    token = request.form['token']

    # Get an instance of the Authentication class
    authentication = restpki_client.get_authentication()

    # Call the complete_with_webpki() method with the token, which finalizes the authentication process. The call
    # yields a ValidationResults object, which denotes whether the authentication was successful or not (we'll use it
    # to render the page accordingly, see below).
    try:
        vr = authentication.complete_with_webpki(token)

        vr_html = str(vr)
        vr_html = vr_html.replace('\n', '<br/>')
        vr_html = vr_html.replace('\t', '&nbsp;&nbsp;&nbsp;&nbsp;')

        user_cert = None

        if vr.is_valid:
            user_cert = authentication.certificate
            # At this point, you have assurance that the certificate is valid according to the SecurityContext specified
            # on the method auth() and that the user is indeed the certificate's subject. Now, you'd typically query
            # your database for a user that matches one of the certificate's fields, such as user_cert.emailAddress or
            # user_cert.pkiBrazil.cpf (the actual field to be used as key depends on your application's business logic)
            # and set the user as authenticated with whatever web security framework your application uses. For
            # demonstration purposes, we'll just render the user's certificate information.
    except Exception as e:
        return render_template('error.html', msg=e)

    return render_template('authentication-action.html', valid=vr.is_valid, user_cert=user_cert, vr_html=vr_html)


# ----------------------------------------------------------------------------------------------------------
@app.route('/pades-signature')
@app.route('/pades-signature/<userfile>')
def pades_signature(userfile=None):
    # If the user was redirected here by /upload (signature with file uploaded by user), the "userfile" route argument
    # will contain the filename under the uploads/ folder. Otherwise (signature with server file), we'll sign a sample
    # document.
    if userfile is None:
        pdf_path = '%s/%s' % (STATIC_FOLDER, TEMPLATE_DOCUMENT)
    else:
        pdf_path = '%s/%s' % (UPLOAD_FOLDER, userfile)

    f = open('static/PdfStamp.png', 'rb')
    pdf_stamp = f.read()
    f.close()

    # Instantiate the PadesSignatureStarter class, responsible for receiving the signature elements and start the
    # signature process
    try:
        signature_starter = PadesSignatureStarter(restpki_client)

        # Set the path of PDF to be signed. The file will be read with the standard open() function, so the same
        # path rules apply.
        signature_starter.set_pdf_path(pdf_path)

        # Set the signature policy
        signature_starter.signature_policy_id = StandardSignaturePolicies.PADES_BASIC

        # Set a SecurityContext to be used to determine trust in the certificate chain
        signature_starter.security_context_id = StandardSecurityContexts.PKI_BRAZIL
        # Note: By changing the SecurityContext above you can accept only certificates from a certain PKI, for instance,
        # ICP-Brasil (lacunarestpki.StandardSecurityContexts.PKI_BRAZIL).

        # Set the visual representation for the signature
        signature_starter.visual_representation = ({
            'text': {
                # The tags {{signerName}} and {{signerNationalId}} will be substituted according to the user's
                # certificate signerName.full name of the signer
                # signerNationalId> if the certificate is ICP-Brasil, contains the signer's CPF
                'text': 'Signed by {{signerName}} ({{signerNationalId}})',
                # Specify that the signing time should also be rendered
                'includeSigningTime': True,
                # Optionally set the horizontal alignment of the text ('Left' or 'Right'), if not set the default is
                # Left
                'horizontalAlign': 'Left'
            },
            'image': {
                # We'll use as background the image static/PdfStamp.png
                'resource': {
                    'content': base64.b64encode(pdf_stamp),
                    'mimeType': 'image/png'
                },
                # Opacity is an integer from 0 to 100 (0 is completely transparent, 100 is completely opaque).
                'opacity': 50,

                # Align the image to the right
                'horizontalAlign': 'Right'
            },
            # Position of the visual representation. We have encapsulated this code in a function to include several
            # possibilities depending on the argument passed to the function. Experiment changing the argument to see
            # different examples of signature positioning. Once you decide which is best for your case, you can place
            # the code directly here.
            'position': get_visual_representation_position(3)
        })

        # Call the start_with_webpki() method, which initiates the signature. This yields the token, a 43-character
        # case-sensitive URL-safe string, which identifies this signature process. We'll use this value to call the
        # signWithRestPki() method on the Web PKI component (see lacuna-web-pki-client.js javascript) and also to
        # complete the signature after the form is submitted (see method pades_signature_action())). This should not be
        # mistaken with the API access token.
        token = signature_starter.start_with_webpki()

    except Exception as e:
        return render_template('error.html', msg=e)

    # The token acquired above can only be used for a single signature attempt. In order to retry the signature it is
    # necessary to get a new token. This can be a problem if the user uses the back button of the browser, since the
    # browser might show a cached page that we rendered previously, with a now stale token. # we force page expiration
    # through HTTP headers to prevent caching of the page.
    response = make_response(render_template('pades-signature.html', token=token, pdf_path=pdf_path))
    response.headers = get_expired_page_headers()
    return response


# ----------------------------------------------------------------------------------------------------------
@app.route('/pades-signature-action', methods=['POST'])
def pades_signature_action():
    # Get the token for this signature (rendered in a hidden input field, see pades-signature.html template)
    token = request.form['token']

    # Instantiate the PadesSignatureFinisher class, responsible for completing the signature process
    signature_finisher = PadesSignatureFinisher(restpki_client)

    # Set the token
    signature_finisher.token = token

    # Call the finish() method, which finalizes the signature process and returns the signed PDF
    signature_finisher.finish()

    # Get information about the certificate used by the user to sign the file. This method must only be called after
    # calling the finish() method.
    signer_cert = signature_finisher.certificate

    # At this point, you'd typically store the signed PDF on your database. For demonstration purposes, we'll
    # store the PDF on a temporary folder publicly accessible and render a link to it.

    filename = '%s.pdf' % (str(uuid.uuid1()))
    signature_finisher.write_signed_pdf(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    return render_template('pades-signature-action.html', signed_file="%s/%s" % (UPLOAD_FOLDER, filename),
                           signer_cert=signer_cert)


# ----------------------------------------------------------------------------------------------------------
@app.route('/uploads/<filename>')
def uploaded_files(filename):
    return send_from_directory('uploads', filename)


# ----------------------------------------------------------------------------------------------------------
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        userfile = request.files['userfile']

        if userfile and allowed_file(userfile.filename):
            filename = secure_filename(userfile.filename)
            filename = '%s_%s' % (str(uuid.uuid1()), filename)
            userfile.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            return redirect('/pades-signature/%s' % filename)
        else:
            return render_template('error.html',
                                   msg="Invalid file type. Allowed file types are: %s" % ",".join(ALLOWED_EXTENSIONS))
    else:
        return render_template('upload.html')


# ----------------------------------------------------------------------------------------------------------
# SUPPORT METHODS
# ----------------------------------------------------------------------------------------------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS


# ----------------------------------------------------------------------------------------------------------
def get_expired_page_headers():
    headers = dict()
    now = datetime.utcnow()
    expires = now - timedelta(seconds=3600)

    headers['Expires'] = expires.strftime("%a, %d %b %Y %H:%M:%S GMT")
    headers['Last-Modified'] = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
    headers['Cache-Control'] = 'private, no-store, max-age=0, no-cache, must-revalidate, post-check=0, pre-check=0'
    headers['Pragma'] = 'no-cache'
    return headers


# ----------------------------------------------------------------------------------------------------------
def get_visual_representation_position(sample_number):
    if sample_number == 1:
        # Example #1: automatic positioning on footnote. This will insert the signature, and future signatures,
        # ordered as a footnote of the last page of the document
        return PadesVisualPositioningPresets.get_footnote(restpki_client)
    elif sample_number == 2:
        # Example #2: get the footnote positioning preset and customize it
        visual_position = PadesVisualPositioningPresets.get_footnote(restpki_client)
        visual_position.auto.container.left = 2.54
        visual_position.auto.container.bottom = 2.54
        visual_position.auto.container.right = 2.54
        return visual_position
    elif sample_number == 3:
        # Example #3: automatic positioning on new page. This will insert the signature, and future signatures,
        # in a new page appended to the end of the document.
        return PadesVisualPositioningPresets.get_new_page(restpki_client)
    elif sample_number == 4:
        # Example #4: get the "new page" positioning preset and customize it
        visual_position = PadesVisualPositioningPresets.get_new_page(restpki_client)
        visual_position.auto.container.left = 2.54
        visual_position.auto.container.top = 2.54
        visual_position.auto.container.right = 2.54
        visual_position.auto.signatureRectangleSize.width = 5
        visual_position.auto.signatureRectangleSize.height = 3
        return visual_position
    elif sample_number == 5:
        # Example #5: manual positioning
        return {
            'pageNumber': 0,
            # zero means the signature will be placed on a new page appended to the end of the document
            'measurementUnits': 'Centimeters',
            # define a manual position of 5cm x 3cm, positioned at 1 inch from the left and bottom margins
            'manual': {
                'left': 2.54,
                'bottom': 2.54,
                'width': 5,
                'height': 3
            }
        }
    elif sample_number == 6:
        # Example #6: custom auto positioning
        return {
            'pageNumber': -1,
            # negative values represent pages counted from the end of the document (-1 is last page)
            'measurementUnits': 'Centimeters',
            'auto': {
                # Specification of the container where the signatures will be placed, one after the other
                'container': {
                    # Specifying left and right (but no width) results in a variable-width container with the given
                    # margins
                    'left': 2.54,
                    'right': 2.54,
                    # Specifying bottom and height (but no top) results in a bottom-aligned fixed-height container
                    'bottom': 2.54,
                    'height': 12.31
                },
                # Specification of the size of each signature rectangle
                'signatureRectangleSize': {
                    'width': 5,
                    'height': 3
                },
                # The signatures will be placed in the container side by side. If there's no room left, the
                # signatures will "wrap" to the next row. The value below specifies the vertical distance between
                # rows
                'rowSpacing': 1
            }
        }
    else:
        return None


# ----------------------------------------------------------------------------------------------------------
# STARTUP CODE
# ----------------------------------------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)