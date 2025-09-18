import os
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

from flask import Flask, render_template_string, request, redirect, session
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import json, unicodedata, re

app = Flask(__name__)
app.secret_key = "REPLACE_WITH_SECRET_KEY"

KEYWORD_FILE = "keywords.txt"
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

HTML_TEMPLATE = """
<!doctype html>
<title>YouTube Anti Spam</title>
<h2>Login dulu</h2>
{% if not logged_in %}
<a href="/login">Login dengan Google</a>
{% else %}
<h3>Masukkan Video ID</h3>
<form method="post">
    <input type="text" name="video_id" placeholder="Video ID" required>
    <button type="submit">Ambil & Deteksi Komentar</button>
</form>
{% if comments %}
<h3>Hasil Deteksi Spam</h3>
<p>Total komentar: <b>{{ total_comments }}</b></p>
<p>Spam terdeteksi: <b>{{ total_spam }}</b></p>
<ul>
{% for c in comments %}
    <li>{{ "[SPAM]" if c in spam_comments else "[OK]" }} {{ c }}
    {% if c in spam_comments and show_delete %}
        <a href="/delete?comment_id={{ comment_ids[c] }}">[Hapus]</a>
    {% endif %}
    </li>
{% endfor %}
</ul>
{% endif %}
{% endif %}
"""

# Load keywords
if not os.path.exists(KEYWORD_FILE):
    print(f"{KEYWORD_FILE} tidak ditemukan!")
    exit()
with open(KEYWORD_FILE, "r", encoding="utf-8") as f:
    keywords = [x.strip().lower() for x in f.readlines() if x.strip()]

def normalize_text(text):
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s]", "", text)
    return text.lower()

@app.route("/login")
def login():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:5000/oauth2callback"
    )
    auth_url, _ = flow.authorization_url(prompt="consent")
    return redirect(auth_url)

@app.route("/oauth2callback")
def callback():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:5000/oauth2callback"
    )
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session["credentials"] = credentials.to_json()
    return redirect("/")

@app.route("/", methods=["GET", "POST"])
def index():
    logged_in = "credentials" in session
    comments = []
    spam_comments = []
    comment_ids = {}
    show_delete = True
    total_comments = 0
    total_spam = 0

    if logged_in and request.method == "POST":
        video_id = request.form["video_id"]
        creds_data = json.loads(session["credentials"])
        creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
        youtube = build("youtube", "v3", credentials=creds)

        request_comments = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,
            textFormat="plainText"
        )
        while request_comments:
            response = request_comments.execute()
            for item in response.get("items", []):
                comment = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
                author = item["snippet"]["topLevelComment"]["snippet"]["authorDisplayName"]
                cid = item["snippet"]["topLevelComment"]["id"]
                full_comment = f"@{author}: {comment}"
                comments.append(full_comment)
                comment_ids[full_comment] = cid
                total_comments += 1
                normalized = normalize_text(comment)
                if any(kw in normalized for kw in keywords):
                    spam_comments.append(full_comment)
                    total_spam += 1
            request_comments = youtube.commentThreads().list_next(request_comments, response)

    return render_template_string(
        HTML_TEMPLATE,
        logged_in=logged_in,
        comments=comments,
        spam_comments=spam_comments,
        comment_ids=comment_ids,
        show_delete=show_delete,
        total_comments=total_comments,
        total_spam=total_spam
    )

@app.route("/delete")
def delete_comment():
    if "credentials" not in session:
        return redirect("/")
    comment_id = request.args.get("comment_id")
    creds_data = json.loads(session["credentials"])
    creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
    youtube = build("youtube", "v3", credentials=creds)
    try:
        youtube.comments().setModerationStatus(
            id=comment_id,
            moderationStatus="rejected"
        ).execute()
        return "<p>Berhasil dihapus!</p><a href='/'>Kembali</a>"
    except Exception as e:
        return f"<p>Error: {e}</p><a href='/'>Kembali</a>"

if __name__ == "__main__":
    app.run(debug=True)
