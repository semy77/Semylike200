from flask import Flask, request, jsonify
import json, os, aiohttp, asyncio, requests, binascii, random
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import like_pb2, like_count_pb2, uid_generator_pb2
from google.protobuf.message import DecodeError

app = Flask(__name__)

# ✅ Files ke paths
LIKES_TOKENS_FILE = 'token_ind.json'
VISIT_TOKENS_FILE = 'visit_ind.json'

# ✅ Universally file se tokens load karne ka function
def get_tokens_from_file(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                tokens = [item["token"] for item in data if "token" in item]
                return tokens
        except Exception as e:
            print(f"Error reading token file ({file_path}): {e}")
            return []
    return []

# ✅ Tweak/Encryption Functions
def encrypt_message(plaintext):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode()

def create_uid_proto(uid):
    pb = uid_generator_pb2.uid_generator()
    pb.saturn_ = int(uid)
    pb.garena = 1
    return pb.SerializeToString()

def create_like_proto(uid):
    pb = like_pb2.like()
    pb.uid = int(uid)
    return pb.SerializeToString()

def decode_protobuf(binary):
    try:
        pb = like_count_pb2.Info()
        pb.ParseFromString(binary)
        return pb
    except DecodeError:
        return None

# ✅ Profile Visit (Random token use karega)
def make_request(enc_uid, token):
    url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB53"
    }
    try:
        res = requests.post(url, data=bytes.fromhex(enc_uid), headers=headers, verify=False)
        return decode_protobuf(res.content)
    except Exception as e:
        print(f"Error in profile visit request: {e}")
        return None

# ✅ Likes Send Karne Ke Liye Request
async def send_request(enc_uid, token):
    url = "https://client.ind.freefiremobile.com/LikeProfile"
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB53"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=bytes.fromhex(enc_uid), headers=headers, ssl=False) as r:
                return r.status
    except Exception as e:
        print(f"Error in send_request: {e}")
        return None

# ✅ Async send likes (Sirf 215 random tokens select karega)
async def send_likes(uid, tokens):
    enc_uid = encrypt_message(create_like_proto(uid))
    
    # 👈 Agar tokens 215 se zyada hain, toh koi bhi 215 random select karega.
    # Agar 215 se kam hain, toh saare tokens use karega bina crash hue.
    target_limit = min(len(tokens), 215)
    selected_tokens = random.sample(tokens, target_limit)
    
    tasks = [send_request(enc_uid, token) for token in selected_tokens]
    return await asyncio.gather(*tasks)

# ✅ Main Route / Endpoint
@app.route('/like', methods=['GET'])
def like_handler():
    uid = request.args.get("uid")
    if not uid:
        return jsonify({"error": "Missing UID"}), 400

    try:
        # 1️⃣ Profile Visit tokens load karein
        visit_tokens = get_tokens_from_file(VISIT_TOKENS_FILE)
        if not visit_tokens:
            return jsonify({"error": "No valid visit tokens found in visit_ind.json"}), 401

        # 2️⃣ Likes tokens load karein
        like_tokens = get_tokens_from_file(LIKES_TOKENS_FILE)
        if not like_tokens:
            return jsonify({"error": "No valid like tokens found in token_ind.json"}), 401

        # 👈 Visit ke liye list me se koi bhi Ek Random Token select karega
        random_visit_token = random.choice(visit_tokens)
        
        # Player info check (Random token use ho raha hai)
        enc_uid = encrypt_message(create_uid_proto(uid))
        before = make_request(enc_uid, random_visit_token)
        if not before:
            return jsonify({"error": "Failed to retrieve player info"}), 500

        before_data = json.loads(MessageToJson(before))
        likes_before = int(before_data.get("AccountInfo", {}).get("Likes", 0))
        nickname = before_data.get("AccountInfo", {}).get("PlayerNickname", "Unknown")

        # 3️⃣ Asynchronous likes send karne ka process (Limited to 215)
        responses = asyncio.run(send_likes(uid, like_tokens))
        success_count = sum(1 for r in responses if r == 200)

        # Likes ke baad ka data check (Dubara ek random token pick karega safety ke liye)
        random_visit_token_after = random.choice(visit_tokens)
        after = make_request(enc_uid, random_visit_token_after)
        likes_after = likes_before
        if after:
            after_data = json.loads(MessageToJson(after))
            likes_after = int(after_data.get("AccountInfo", {}).get("Likes", 0))

        return jsonify({
            "PlayerNickname": nickname,
            "UID": uid,
            "LikesbeforeCommand": likes_before,
            "LikesafterCommand": likes_after,
            "LikesGivenByAPI": likes_after - likes_before,
            "SuccessfulRequests": success_count,
            "TotalRequests": min(len(like_tokens), 215),  # 👈 Yahan ab max 215 hi dikhayega
            "status": 1 if likes_after > likes_before else 2,
            "DEVELOPER TELEGRAM": "@SEMY0HERE"
        })

    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/')
def home():
    return jsonify({"status": "online", "message": "Like API with Random 215 Token Limit is running! 🔄 ✅"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
