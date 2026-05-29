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
            app.logger.error(f"Error reading token file ({file_path}): {e}")
            return []
    return []

# ✅ Tweak/Encryption Functions
def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode()
    except Exception as e:
        app.logger.error(f"Encryption failed: {e}")
        return None

def create_uid_proto(uid):
    try:
        pb = uid_generator_pb2.uid_generator()
        pb.saturn_ = int(uid)
        pb.garena = 1
        return pb.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating uid protobuf: {e}")
        return None

def create_like_proto(uid):
    try:
        pb = like_pb2.like()
        pb.uid = int(uid)
        return pb.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating like protobuf: {e}")
        return None

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
        app.logger.error(f"Error in profile visit request: {e}")
        return None

# ✅ High Success Send Request (Ab yeh main session reuse karega)
async def send_request(session, enc_uid, token):
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
        # Naya session open karne ke bajaye pass kiya hua main session use ho raha hai
        async with session.post(url, data=bytes.fromhex(enc_uid), headers=headers, ssl=False) as r:
            if r.status != 200:
                app.logger.error(f"Request failed with status code: {r.status}")
            return r.status
    except Exception as e:
        app.logger.error(f"Exception in send_request: {e}")
        return None

# ✅ High Success Async Send Likes (Single Session + 50-50 Batches)
async def send_likes(uid, tokens):
    protobuf_data = create_like_proto(uid)
    if protobuf_data is None:
        return []
        
    enc_uid = encrypt_message(protobuf_data)
    if enc_uid is None:
        return []
    
    # Max 215 random tokens select karega
    target_limit = min(len(tokens), 215)
    selected_tokens = random.sample(tokens, target_limit)
    
    batch_size = 50  # 50-50 ka batch size
    responses = []
    
    # Pure process ke liye sirf EK baar ClientSession create hoga (Success badhane ka secret)
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(selected_tokens), batch_size):
            batch = selected_tokens[i:i+batch_size]
            
            # Har request ko same session pass kiya ja raha hai
            tasks = [send_request(session, enc_uid, token) for token in batch]
            
            # Tasks execute honge aur exceptions handle honge taaki crash na ho
            batch_responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            for res in batch_responses:
                if isinstance(res, int):  # Agar response code integer hai (like 200, 400)
                    responses.append(res)
                else:
                    responses.append(None)
            
            # Agar aage aur batches hain toh server safety ke liye 0.5 sec ka delay
            if i + batch_size < len(selected_tokens):
                await asyncio.sleep(0.5) 
                
    return responses

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

        # Visit ke liye list me se koi bhi Ek Random Token select karega
        random_visit_token = random.choice(visit_tokens)
        
        # Player info check (Before)
        enc_uid_visit = encrypt_message(create_uid_proto(uid))
        if not enc_uid_visit:
            return jsonify({"error": "Encryption failed for player info"}), 500
            
        before = make_request(enc_uid_visit, random_visit_token)
        if not before:
            return jsonify({"error": "Failed to retrieve player info"}), 500

        before_data = json.loads(MessageToJson(before))
        likes_before = int(before_data.get("AccountInfo", {}).get("Likes", 0))
        nickname = before_data.get("AccountInfo", {}).get("PlayerNickname", "Unknown")

        # 3️⃣ Asynchronous likes send karne ka High-Success process
        responses = asyncio.run(send_likes(uid, like_tokens))
        success_count = sum(1 for r in responses if r == 200)

        # Likes ke baad ka data check (After)
        random_visit_token_after = random.choice(visit_tokens)
        after = make_request(enc_uid_visit, random_visit_token_after)
        likes_after = likes_before
        if after:
            after_data = json.loads(MessageToJson(after))
            likes_after = int(after_data.get("AccountInfo", {}).get("Likes", 0))

        # Kitne total tokens bhejے gye uski counting ke liye
        actual_total_sent = min(len(like_tokens), 215)

        return jsonify({
            "DEVELOPER TELEGRAM": "@SEMY0HERE",
            "LikesGivenByAPI": likes_after - likes_before,
            "LikesafterCommand": likes_after,
            "LikesbeforeCommand": likes_before,
            "PlayerNickname": nickname,
            "SuccessfulRequests": success_count,
            "TotalRequests": actual_total_sent,
            "UID": uid,
            "status": 1 if likes_after > likes_before else 2
        })

    except Exception as e:
        app.logger.error(f"Internal server error: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/')
def home():
    return jsonify({"status": "online", "message": "High Success Like API (50-Batch / Max 215) is running! 🚀 ✅"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
